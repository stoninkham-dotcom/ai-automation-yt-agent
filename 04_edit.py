import datetime
import glob
import math
import os
import random
import re
import shutil
import subprocess

from PIL import Image, ImageDraw

SEGMENT_DURATION = 3.2
OUT_W = 1080
OUT_H = 1920
FPS = 30
BGM_PATH = os.path.join("assets", "bgm.mp3")
CHAR_PATH = os.path.join("assets", "character.png")


def get_today_folder() -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return os.path.join("scripts", now_utc.strftime("%Y-%m-%d"))


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def get_video_duration(video_path: str) -> float:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return max(0.0, float(res.stdout.strip()))
    except Exception:
        return 0.0


def build_subtle_clip_filter(idx: int, seg_dur: float) -> str:
    # Subtle, viewer-friendly zoom (max 3%) + gentle pan
    dur = max(0.5, seg_dur)
    if idx % 2 == 0:
        scale_expr = f"1.0+0.03*(t/{dur})"
    else:
        scale_expr = f"1.03-0.03*(t/{dur})"

    pan_x = "0.5+0.015*sin(t*0.9)" if idx % 3 == 0 else "0.5-0.015*cos(t*0.8)"
    pan_y = "0.5+0.012*cos(t*0.8)"

    return (
        f"fps={FPS},"
        f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame,"
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:eval=frame,"
        f"crop={OUT_W}:{OUT_H}:x='(iw-{OUT_W})*({pan_x})':y='(ih-{OUT_H})*({pan_y})',"
        f"eq=contrast=1.08:brightness=0.01:saturation=1.12,format=yuv420p"
    )


def create_character_frames(temp_dir: str) -> tuple[str, str]:
    """Creates two crisp character PNGs (closed mouth & open talking mouth) if assets/character.png isn't present."""
    closed_png = os.path.join(temp_dir, "char_closed.png")
    open_png = os.path.join(temp_dir, "char_open.png")

    if os.path.exists(CHAR_PATH) and os.path.getsize(CHAR_PATH) > 0:
        base = Image.open(CHAR_PATH).convert("RGBA").resize((270, 270), Image.Resampling.LANCZOS)
        base.save(closed_png)
        base.save(open_png)
        return closed_png, open_png

    def draw_char(mouth_open: bool, out_file: str):
        w, h = 270, 270
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Soft glow ring behind character
        d.ellipse([28, 28, 242, 242], fill=(24, 28, 42, 210), outline=(99, 102, 241, 255), width=5)

        # Hoodie / shoulders
        d.rounded_rectangle([54, 168, 216, 252], radius=42, fill=(37, 99, 235, 255))

        # Head
        d.ellipse([74, 56, 196, 178], fill=(251, 191, 146, 255), outline=(30, 30, 35, 255), width=4)

        # Hair top
        d.pieslice([72, 46, 198, 128], start=180, end=360, fill=(24, 24, 32, 255))

        # Glasses / eyes
        d.ellipse([98, 104, 124, 126], fill=(255, 255, 255, 255), outline=(25, 25, 30, 255), width=3)
        d.ellipse([146, 104, 172, 126], fill=(255, 255, 255, 255), outline=(25, 25, 30, 255), width=3)
        d.ellipse([108, 111, 118, 121], fill=(20, 20, 25, 255))
        d.ellipse([154, 111, 164, 121], fill=(20, 20, 25, 255))

        # Mouth (talking animation)
        if mouth_open:
            d.ellipse([118, 138, 152, 160], fill=(220, 38, 38, 255), outline=(25, 25, 30, 255), width=3)
        else:
            d.rounded_rectangle([120, 144, 150, 152], radius=4, fill=(25, 25, 30, 255))

        img.save(out_file)

    draw_char(False, closed_png)
    draw_char(True, open_png)
    return closed_png, open_png


def build_captions_srt(folder: str, audio_dur: float, temp_dir: str) -> str | None:
    narration_path = os.path.join(folder, "narration.txt")
    if not os.path.exists(narration_path):
        return None

    with open(narration_path, "r", encoding="utf-8", errors="ignore") as f:
        text = re.sub(r"\s+", " ", f.read()).strip()

    if not text:
        return None

    words = text.split(" ")
    chunks = []
    chunk_size = 4
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i : i + chunk_size]))

    if not chunks:
        return None

    def fmt_ts(sec: float) -> str:
        sec = max(0.0, min(sec, audio_dur))
        ms = int((sec - int(sec)) * 1000)
        s = int(sec) % 60
        m = (int(sec) // 60) % 60
        h = int(sec) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    srt_path = os.path.join(temp_dir, "captions.srt")
    dur_per_chunk = audio_dur / len(chunks)
    with open(srt_path, "w", encoding="utf-8") as out:
        for idx, phrase in enumerate(chunks, start=1):
            start_t = (idx - 1) * dur_per_chunk
            end_t = min(audio_dur, idx * dur_per_chunk)
            out.write(f"{idx}\n{fmt_ts(start_t)} --> {fmt_ts(end_t)}\n{phrase.upper()}\n\n")

    return srt_path


def render_segment(clip_path: str, start_sec: float, seg_dur: float, out_path: str, idx: int):
    vf = build_subtle_clip_filter(idx, seg_dur)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.2f}",
        "-t",
        f"{seg_dur + 0.35:.2f}",
        "-i",
        clip_path,
        "-an",
        "-vf",
        vf,
        "-t",
        f"{seg_dur:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"Segment fail ({clip_path}): {res.stderr[-300:]}")


def generate_fallback_bgm(duration: float, out_bgm: str):
    dur = max(1.0, duration + 1.0)
    filter_complex = (
        f"anoisesrc=color=pink:amplitude=0.05:duration={dur},"
        f"lowpass=f=240,aformat=channel_layouts=stereo[pad];"
        f"sine=frequency=110:duration={dur},tremolo=f=2.2:d=0.5,lowpass=f=280,volume=0.045[bass];"
        f"[pad][bass]amix=inputs=2:duration=first,afade=t=in:st=0:d=0.8,afade=t=out:st={max(0.0, dur-1.0)}:d=1.0[bgm]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-filter_complex",
            filter_complex,
            "-map",
            "[bgm]",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            out_bgm,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def mix_voice_and_bgm(voice_path: str, audio_dur: float, temp_dir: str) -> str:
    mixed_audio = os.path.join(temp_dir, "mixed_audio.aac")
    if os.path.exists(BGM_PATH) and os.path.getsize(BGM_PATH) > 0:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            voice_path,
            "-stream_loop",
            "-1",
            "-i",
            BGM_PATH,
            "-filter_complex",
            f"[1:a]volume=0.16,afade=t=out:st={max(0.0, audio_dur-1.0)}:d=1.0[bgm];"
            f"[0:a]volume=1.0[voice];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[outa]",
            "-map",
            "[outa]",
            "-t",
            f"{audio_dur:.2f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            mixed_audio,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return mixed_audio

    fallback_bgm = os.path.join(temp_dir, "fallback_bgm.aac")
    generate_fallback_bgm(audio_dur, fallback_bgm)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        voice_path,
        "-i",
        fallback_bgm,
        "-filter_complex",
        "[0:a]volume=1.0[voice];[1:a]volume=1.0[bgm];[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[outa]",
        "-map",
        "[outa]",
        "-t",
        f"{audio_dur:.2f}",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        mixed_audio,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return mixed_audio


def add_character_and_captions(merged_video: str, srt_path: str | None, temp_dir: str) -> str:
    closed_png, open_png = create_character_frames(temp_dir)
    styled_video = os.path.join(temp_dir, "styled_video.mp4")

    # Animated talking character toggled every ~0.22s with gentle vertical bounce
    fc_parts = [
        f"[1:v]loop=-1:size=1:start=0,setpts=PTS-STARTPTS[c_closed]",
        f"[2:v]loop=-1:size=1:start=0,setpts=PTS-STARTPTS[c_open]",
        f"[c_closed][c_open]overlay=x=0:y=0:enable='lt(mod(t,0.44),0.22)'[char_talk]",
        f"[0:v][char_talk]overlay=x={OUT_W}-w-36:y={OUT_H}-h-240+'10*sin(t*5)':shortest=1[v_char]",
    ]

    if srt_path and os.path.exists(srt_path):
        safe_srt = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")
        style = "FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=2,Shadow=1,Alignment=2,MarginV=520"
        fc_parts.append(f"[v_char]subtitles='{safe_srt}':force_style='{style}',format=yuv420p[v_out]")
        map_v = "[v_out]"
    else:
        fc_parts.append("[v_char]format=yuv420p[v_out]")
        map_v = "[v_out]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        merged_video,
        "-i",
        closed_png,
        "-i",
        open_png,
        "-filter_complex",
        ";".join(fc_parts),
        "-map",
        map_v,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        styled_video,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(styled_video):
        # Fallback without captions if subtitle filter has any font issue on runner
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            merged_video,
            "-i",
            closed_png,
            "-i",
            open_png,
            "-filter_complex",
            ";".join(fc_parts[:4] + ["[v_char]format=yuv420p[v_out]"]),
            "-map",
            "[v_out]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            styled_video,
        ]
        subprocess.run(fallback_cmd, check=True, capture_output=True, text=True)

    return styled_video


def main():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg/ffprobe nahi mila.")

    folder = get_today_folder()
    voice_path = os.path.join(folder, "voiceover.mp3")
    clips_dir = os.path.join(folder, "clips")

    if not os.path.exists(voice_path):
        raise FileNotFoundError(f"{voice_path} nahi mila.")

    clips = sorted(glob.glob(os.path.join(clips_dir, "*.mp4")))
    if not clips:
        raise FileNotFoundError(f"{clips_dir} mein koi .mp4 clip nahi mili.")

    random.shuffle(clips)
    audio_dur = get_audio_duration(voice_path)
    num_segments = max(1, math.ceil(audio_dur / SEGMENT_DURATION))

    temp_dir = os.path.join(folder, "_edit_tmp")
    os.makedirs(temp_dir, exist_ok=True)

    seg_files = []
    try:
        for i in range(num_segments):
            remaining = audio_dur - (i * SEGMENT_DURATION)
            if remaining <= 0.15:
                break
            seg_dur = min(SEGMENT_DURATION, remaining)
            clip = clips[i % len(clips)]
            clip_dur = get_video_duration(clip)
            max_start = max(0.0, clip_dur - seg_dur - 0.5)
            start_offset = ((i * 1.7) % (max_start + 0.01)) if max_start > 0 else 0.0
            seg_out = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            render_segment(clip, start_offset, seg_dur, seg_out, i)
            seg_files.append(seg_out)

        list_txt = os.path.join(temp_dir, "concat.txt")
        with open(list_txt, "w", encoding="utf-8") as f:
            for p in seg_files:
                abs_p = os.path.abspath(p).replace("\\", "/")
                f.write(f"file '{abs_p}'\n")

        merged_video = os.path.join(temp_dir, "merged_no_audio.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_txt,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                merged_video,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        srt_path = build_captions_srt(folder, audio_dur, temp_dir)
        styled_video = add_character_and_captions(merged_video, srt_path, temp_dir)

        mixed_audio = mix_voice_and_bgm(voice_path, audio_dur, temp_dir)
        final_out = os.path.join(folder, "final_short.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                styled_video,
                "-i",
                mixed_audio,
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-shortest",
                final_out,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        size_mb = os.path.getsize(final_out) / (1024 * 1024)
        print(f"Final video ready: {final_out} ({size_mb:.2f} MB, {audio_dur:.1f}s)")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
                                                            

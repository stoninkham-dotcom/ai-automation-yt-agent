import datetime
import glob
import math
import os
import random
import shutil
import subprocess

SEGMENT_DURATION = 3.2
OUT_W = 1080
OUT_H = 1920
FPS = 30
BGM_PATH = os.path.join("assets", "bgm.mp3")


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


def build_smooth_clip_filter(idx: int, seg_dur: float) -> str:
    # Smooth continuous motion on real video frames without stiff zoompan freeze
    zoom_in = (idx % 2 == 0)
    if zoom_in:
        scale_expr = f"1.0+0.08*(t/{max(0.5, seg_dur)})"
    else:
        scale_expr = f"1.08-0.08*(t/{max(0.5, seg_dur)})"

    pan_x = "0.5+0.04*sin(t*1.2)" if idx % 3 == 0 else "0.5-0.04*cos(t*1.1)"
    pan_y = "0.5+0.03*cos(t*1.0)"

    return (
        f"fps={FPS},"
        f"scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame,"
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:eval=frame,"
        f"crop={OUT_W}:{OUT_H}:x='(iw-{OUT_W})*({pan_x})':y='(ih-{OUT_H})*({pan_y})':eval=frame,"
        f"eq=contrast=1.10:brightness=0.015:saturation=1.16,format=yuv420p"
    )


def render_segment(clip_path: str, start_sec: float, seg_dur: float, out_path: str, idx: int):
    vf = build_smooth_clip_filter(idx, seg_dur)
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
    # Soft warm low-end pulse/pad so video never feels dead silent
    dur = max(1.0, duration + 1.0)
    filter_complex = (
        f"anoisesrc=color=pink:amplitude=0.04:duration={dur},"
        f"lowpass=f=220,aformat=channel_layouts=stereo[pad];"
        f"sine=frequency=110:duration={dur},tremolo=f=2.0:d=0.45,lowpass=f=260,volume=0.035[bass];"
        f"[pad][bass]amix=inputs=2:duration=first,afade=t=in:st=0:d=1.0,afade=t=out:st={max(0.0, dur-1.2)}:d=1.2[bgm]"
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
            f"[1:a]volume=0.14,afade=t=out:st={max(0.0, audio_dur-1.2)}:d=1.2[bgm];"
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

        mixed_audio = mix_voice_and_bgm(voice_path, audio_dur, temp_dir)
        final_out = os.path.join(folder, "final_short.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                merged_video,
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
            

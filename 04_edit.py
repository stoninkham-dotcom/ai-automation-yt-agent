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


def build_segment_filter(idx: int, seg_dur: float) -> str:
    frames = max(1, int(round(seg_dur * FPS)))
    zoom_in = (idx % 2 == 0)
    if zoom_in:
        z_expr = f"1+0.12*(on/{max(1, frames)})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        z_expr = f"1.12-0.12*(on/{max(1, frames)})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"scale={OUT_W * 2}:{OUT_H * 2}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W * 2}:{OUT_H * 2},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={OUT_W}x{OUT_H}:fps={FPS},"
        f"eq=contrast=1.08:brightness=0.01:saturation=1.12,format=yuv420p"
    )


def render_segment(clip_path: str, start_sec: float, seg_dur: float, out_path: str, idx: int):
    vf = build_segment_filter(idx, seg_dur)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.2f}",
        "-t",
        f"{seg_dur + 0.5:.2f}",
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
        "veryfast",
        "-crf",
        "22",
        "-r",
        str(FPS),
        out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"Segment fail ({clip_path}): {res.stderr[-300:]}")


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
            start_offset = (i * 1.3) % 4.0
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
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                merged_video,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        final_out = os.path.join(folder, "final_short.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                merged_video,
                "-i",
                voice_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
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
  

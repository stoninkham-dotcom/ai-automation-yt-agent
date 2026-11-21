import asyncio
import datetime
import os
import shutil
import subprocess
import edge_tts

VOICES_TO_TRY = [
    "en-US-AndrewNeural",
    "en-US-ChristopherNeural",
    "en-GB-RyanNeural",
    "en-US-AriaNeural",
]

PER_VOICE_TIMEOUT = 25
VOICE_RATE = "+15%"


def get_today_folder() -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    date_folder = now_utc.strftime("%Y-%m-%d")
    return os.path.join("scripts", date_folder)


async def try_single_voice(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=VOICE_RATE,
        pitch="+1Hz",
    )
    await communicate.save(output_path)


def trim_dead_air(mp3_path: str):
    if not shutil.which("ffmpeg"):
        print("ffmpeg nahi mila, silence cut skip kiya gaya.")
        return

    temp_raw = mp3_path + ".raw.mp3"
    os.replace(mp3_path, temp_raw)

    # Lambe pauses/silence kat kar voice ko Shorts ke liye tight banana
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        temp_raw,
        "-af",
        "silenceremove=start_periods=1:start_silence=0.15:start_threshold=-42dB:stop_periods=-1:stop_silence=0.18:stop_threshold=-42dB",
        "-b:a",
        "192k",
        mp3_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        os.remove(temp_raw)
        print("Lambe pauses/silence cut kar diye gaye hain.")
    else:
        os.replace(temp_raw, mp3_path)
        print("Silence cut nahi ho saka, original audio rakha gaya.")


async def generate_with_fallback(text: str, output_path: str):
    errors = []
    for voice in VOICES_TO_TRY:
        try:
            print(f"Trying voice: {voice} (timeout={PER_VOICE_TIMEOUT}s)...")
            await asyncio.wait_for(
                try_single_voice(text, output_path, voice),
                timeout=PER_VOICE_TIMEOUT,
            )
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                trim_dead_air(output_path)
                print(f"Success with voice: {voice}")
                return voice
        except asyncio.TimeoutError:
            msg = f"{voice} timed out after {PER_VOICE_TIMEOUT}s"
            print(msg)
            errors.append(msg)
        except Exception as exc:
            msg = f"{voice} failed -> {exc}"
            print(msg)
            errors.append(msg)
    raise RuntimeError("Koi bhi voice kaam nahi kiya:\n" + "\n".join(errors))


def main():
    folder = get_today_folder()
    input_file = os.path.join(folder, "narration.txt")
    output_file = os.path.join(folder, "voiceover.mp3")

    if not os.path.exists(input_file):
        raise FileNotFoundError(f"{input_file} nahi mila. Pehle script.py chalayein.")

    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        raise ValueError("narration.txt khali hai.")

    used_voice = asyncio.run(generate_with_fallback(text, output_file))
    size_kb = os.path.getsize(output_file) / 1024
    print(f"Saved {output_file} ({size_kb:.1f} KB) using voice {used_voice}")


if __name__ == "__main__":
    main()
    

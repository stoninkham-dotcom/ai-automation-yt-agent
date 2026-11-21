import asyncio
import datetime
import os
import edge_tts

VOICES_TO_TRY = [
    "en-US-AndrewNeural",
    "en-US-ChristopherNeural",
    "en-GB-RyanNeural",
    "en-US-AriaNeural",
]

PER_VOICE_TIMEOUT = 20


def get_today_folder() -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    date_folder = now_utc.strftime("%Y-%m-%d")
    return os.path.join("scripts", date_folder)


async def try_single_voice(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+4%",
        pitch="+0Hz",
    )
    await communicate.save(output_path)


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
        

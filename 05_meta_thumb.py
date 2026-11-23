import json
import os
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

META_DIR = Path("output/meta")
THUMB_DIR = Path("output/thumbnails")
META_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
]


def get_context():
    for path in [Path("output/script_data.json"), Path("script_output.json")]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {
        "topic": "Daily focus and habit",
        "script": os.environ.get("VIDEO_SCRIPT", ""),
    }


def fallback_meta(ctx: dict) -> dict:
    topic = str(ctx.get("topic") or "Daily Focus Habit").strip()
    short_topic = topic[:38]
    return {
        "title": f"{short_topic} #Shorts"[:65],
        "description": f"Simple daily shift for {short_topic.lower()}. Try it today and stay consistent.\n#Shorts #DailyHabits #Mindset",
        "keywords": ["daily habits", "focus", "productivity", "mindset", "morning routine", "discipline", "self improvement", "shorts"],
        "hashtags": ["#Shorts", "#DailyHabits", "#Mindset"],
        "thumb_text": short_topic[:28] or "Watch This Today",
    }


def make_meta(ctx: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("No GEMINI_API_KEY found, using local fallback metadata.")
        return fallback_meta(ctx)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=15000),
    )
    prompt = f"""
    Write natural, human-sounding YouTube Shorts metadata for US/UK viewers from this context:
    {json.dumps(ctx, ensure_ascii=False)}

    Rules:
    - Never mention AI, bots, or automation.
    - Keep tone human, direct, and engaging.
    - Return ONLY JSON with keys:
      "title" (under 65 chars, include #Shorts),
      "description" (2 short lines + 3 hashtags),
      "keywords" (list of 8-10 words without '#'),
      "hashtags" (list of 3-4 tags starting with '#'),
      "thumb_text" (3 to 5 bold words).
    """

    for model_name in GEMINI_MODELS:
        try:
            print(f"Trying {model_name} (15s timeout)...")
            res = client.models.generate_content(model=model_name, contents=prompt)
            text = (res.text or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
            print(f"Metadata generated using {model_name}")
            return {
                "title": str(data.get("title", "Quick Habit Shift #Shorts")).strip()[:100],
                "description": str(data.get("description", "")).strip(),
                "keywords": [str(k).lstrip("#").strip() for k in data.get("keywords", []) if str(k).strip()][:10],
                "hashtags": [
                    (str(h).strip() if str(h).strip().startswith("#") else "#" + str(h).strip())
                    for h in data.get("hashtags", ["#Shorts"])
                ][:4],
                "thumb_text": str(data.get("thumb_text", "Watch This Today")).strip(),
            }
        except Exception as e:
            print(f"Skipping {model_name}: {e}")

    print("All Gemini models timed out/failed; using fast fallback metadata.")
    return fallback_meta(ctx)


def make_thumb(headline: str, out_file: Path = THUMB_DIR / "thumbnail.jpg") -> Path:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (16, 20, 30))
    draw = ImageDraw.Draw(img)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 88) if os.path.exists(font_path) else ImageFont.load_default()

    words = headline.upper().split()
    lines, line = [], ""
    for word in words:
        test = f"{line} {word}".strip()
        box = draw.textbbox((0, 0), test, font=font)
        if (box[2] - box[0]) <= 860:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)

    start_y = (h - len(lines) * 110) // 2
    for i, l in enumerate(lines):
        box = draw.textbbox((0, 0), l, font=font)
        x = (w - (box[2] - box[0])) // 2
        y = start_y + i * 110
        color = (255, 205, 65) if i == len(lines) - 1 else (255, 255, 255)
        draw.text((x + 4, y + 4), l, font=font, fill=(0, 0, 0))
        draw.text((x, y), l, font=font, fill=color)

    img.save(out_file, "JPEG", quality=92)
    return out_file


def main():
    ctx = get_context()
    meta = make_meta(ctx)
    thumb = make_thumb(meta["thumb_text"])
    meta["thumbnail_path"] = str(thumb)
    out_json = META_DIR / "metadata.json"
    out_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved:", out_json, "and", thumb)


if __name__ == "__main__":
    main()
    

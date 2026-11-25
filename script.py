from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import datetime
import json
import os
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise ValueError("GEMINI_API_KEY secret missing ya empty hai.")

client = genai.Client(api_key=API_KEY)

MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

DAILY_ANGLES = [
    "Why 90% of clinic AI automations fail in week one—and the exact 2-step fix that saves 15 hours a week",
    "The hidden cost of slow patient and client follow-ups—and how smart AI workflows close leads 24/7",
    "Stop using generic AI chatbots on real businesses: how to build calm, human-sounding systems US/UK buyers trust",
    "One workflow vs ten prompts: how a single automated intake-to-booking pipeline beats manual admin every day",
    "What clinics and agencies get wrong about AI speed—and how to automate without sounding like a robot",
    "From missed calls to booked calendars: a practical breakdown of high-ROI AI operations for service businesses",
    "Why 'set and forget' AI breaks—and how real operators design self-healing automations that scale quietly",
]

now_utc = datetime.datetime.now(datetime.timezone.utc)
date_folder = now_utc.strftime("%Y-%m-%d")
run_day = now_utc.timetuple().tm_yday
TODAY_TOPIC = DAILY_ANGLES[run_day % len(DAILY_ANGLES)]

out_dir = os.path.join("scripts", date_folder)
os.makedirs(out_dir, exist_ok=True)

PROMPT = f"""
You are a top-tier creative director and scriptwriter for a high-performing US/UK tech & AI operations YouTube channel.
Write a punchy, human, high-retention video script on today's angle:
\"{TODAY_TOPIC}\"

Strict quality & retention rules:
- First 3 seconds must hit with a bold contrarian truth or sharp real-world stakes (no \"Hey guys\", no \"In today's fast-paced world\", no \"Let's dive in\").
- Write for spoken ear, not a textbook: short sentences, natural pauses, crisp transitions, zero corporate buzzwords.
- Include clear tension -> mechanism -> proof/reality check -> sharp takeaway so viewers stay through the end.
- Make every run feel fresher, sharper, and more actionable than generic advice.
- Output strictly valid JSON with exact keys:
  \"title\" (curiosity-driven, clean, under 65 chars),
  \"description\" (concise, natural, keyword-smart without spam),
  \"narration\" (full spoken script, ~180-240 words for tight pacing),
  \"scenes\" (list of 4 distinct visual b-roll/scene prompts matching the script beats).
"""

PER_MODEL_TIMEOUT_SEC = 20


def _call_model_once(model_name: str, prompt_text: str) -> str:
    resp = client.models.generate_content(
        model=model_name,
        contents=prompt_text,
    )
    return (resp.text or "").strip() if resp else ""


def parse_json_safely(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                cleaned = candidate
                break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("JSON root is not an object")
    return parsed


def build_fallback_package(topic: str) -> dict:
    narration = (
        "Most AI automations don't fail because the model is weak. They fail because the handoff is messy. "
        "A lead messages at nine at night, gets a generic wall of text, and still waits until morning for a real reply. "
        "Meanwhile, the team has to clean up broken data across three tools before anyone books a slot. "
        "Fix the workflow first. Capture the exact intent, confirm the time window clearly, and route only qualified requests to humans. "
        "When the system handles the repetitive intake cleanly, response time drops from hours to seconds without sounding robotic. "
        "Keep it simple, test the edge cases, and let calm automation carry the routine work."
    )
    return {
        "title": "Why Most AI Workflows Break Fast",
        "description": "How clean intake and reliable routing beat overcomplicated AI setups for daily operations.",
        "narration": narration,
        "scenes": [
            "Modern operations desk at night with calm amber monitor lighting and clean workflow notes, moody cinematic b-roll",
            "Close-up of hands typing a clear schedule confirmation on a laptop in a quiet minimalist office, natural light",
            "Fast-paced montage of incoming messages being sorted neatly into a structured queue, crisp editorial style",
            "Confident operator reviewing a smooth calendar schedule in the morning, clean high-contrast framing",
        ],
    }


def generate_with_fallback(prompt_text: str):
    for model_name in MODELS_TO_TRY:
        print(f"Trying model: {model_name} (timeout={PER_MODEL_TIMEOUT_SEC}s)...")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_call_model_once, model_name, prompt_text)
            raw_text = future.result(timeout=PER_MODEL_TIMEOUT_SEC)
            if raw_text:
                parsed = parse_json_safely(raw_text)
                if parsed.get("narration") and parsed.get("title"):
                    print(f"Success with model: {model_name}")
                    return parsed, model_name
            print(f"{model_name} returned empty/invalid output, moving to next model.")
        except FuturesTimeoutError:
            print(f"{model_name} timed out after {PER_MODEL_TIMEOUT_SEC}s, skipping fast.")
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            print(f"{model_name} failed -> {exc}")
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=False)

    print("All Gemini models timed out or failed; using local fallback script.")
    return build_fallback_package(TODAY_TOPIC), "local-fallback"


data, used_model = generate_with_fallback(PROMPT)

if not isinstance(data.get("scenes"), list) or len(data["scenes"]) == 0:
    data["scenes"] = build_fallback_package(TODAY_TOPIC)["scenes"]

data["used_model"] = used_model
data["daily_angle"] = TODAY_TOPIC
data["date"] = date_folder

narration_path = os.path.join(out_dir, "narration.txt")
package_path = os.path.join(out_dir, "video_package.json")

with open(package_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

with open(narration_path, "w", encoding="utf-8") as f:
    f.write(str(data["narration"]).strip())

print("USED MODEL:", used_model)
print("DATE FOLDER:", out_dir)
print("TITLE:", data["title"])
print(f"Saved {narration_path} and {package_path}")
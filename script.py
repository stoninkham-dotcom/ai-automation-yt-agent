import datetime
import json
import os
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise ValueError("GEMINI_API_KEY secret missing ya empty hai.")

client = genai.Client(api_key=API_KEY)

MODELS_TO_TRY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
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

run_day = datetime.datetime.now(datetime.timezone.utc).timetuple().tm_yday
TODAY_TOPIC = DAILY_ANGLES[run_day % len(DAILY_ANGLES)]

PROMPT = f"""
You are a top-tier creative director and scriptwriter for a high-performing US/UK tech & AI operations YouTube channel.
Write a punchy, human, high-retention video script on today's angle:
"{TODAY_TOPIC}"

Strict quality & retention rules:
- First 3 seconds must hit with a bold contrarian truth or sharp real-world stakes (no "Hey guys", no "In today's fast-paced world", no "Let's dive in").
- Write for spoken ear, not a textbook: short sentences, natural pauses, crisp transitions, zero corporate buzzwords.
- Include clear tension -> mechanism -> proof/reality check -> sharp takeaway so viewers stay through the end.
- Make every run feel fresher, sharper, and more actionable than generic advice.
- Output strictly valid JSON with exact keys:
  "title" (curiosity-driven, clean, under 65 chars),
  "description" (concise, natural, keyword-smart without spam),
  "narration" (full spoken script, ~180-240 words for tight pacing),
  "scenes" (list of 4 distinct visual b-roll/scene prompts matching the script beats).
"""


def generate_with_fallback(prompt_text: str):
    errors = []
    for model_name in MODELS_TO_TRY:
        try:
            print(f"Trying model: {model_name}...")
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt_text,
            )
            if resp and resp.text:
                print(f"Success with model: {model_name}")
                return resp.text.strip(), model_name
        except Exception as exc:
            msg = f"{model_name} failed -> {exc}"
            print(msg)
            errors.append(msg)
    raise RuntimeError("Koi bhi Gemini model kaam nahi kiya:\n" + "\n".join(errors))


raw, used_model = generate_with_fallback(PROMPT)

if raw.startswith("```"):
    raw = raw.split("```", 2)[1]
    if raw.startswith("json"):
        raw = raw[4:]
    raw = raw.strip()

data = json.loads(raw)
data["used_model"] = used_model
data["daily_angle"] = TODAY_TOPIC

with open("video_package.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

with open("narration.txt", "w", encoding="utf-8") as f:
    f.write(data["narration"].strip())

print("USED MODEL:", used_model)
print("DAILY ANGLE:", TODAY_TOPIC)
print("TITLE:", data["title"])
print("Saved narration.txt and video_package.json")

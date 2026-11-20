import json
import os
from google import genai

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise ValueError("GEMINI_API_KEY secret set nahi hai.")

client = genai.Client(api_key=API_KEY)

TOPIC = "How AI automation saves clinics and agencies 15 hours a week without sounding robotic"

PROMPT = f"""
Write a sharp, natural, high-retention YouTube video script for a US/UK audience on:
"{TOPIC}"

Rules:
- Sound like a real human operator sharing practical experience, not a generic AI or hype-bro.
- Short sentences, natural pacing, clear structure: Hook, Problem, Real Solution, Takeaway.
- No filler phrases like "In today's fast-paced world" or "Let's dive in".
- Also give a clean YouTube title, short description, and 4 short visual scene prompts for stock footage.

Return strictly valid JSON with keys:
"title", "description", "narration", "scenes" (list of 4 strings).
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=PROMPT,
)

raw = response.text.strip()
if raw.startswith("```"):
    raw = raw.split("```", 2)[1]
    if raw.startswith("json"):
        raw = raw[4:]
    raw = raw.strip()

data = json.loads(raw)

with open("video_package.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

with open("narration.txt", "w", encoding="utf-8") as f:
    f.write(data["narration"].strip())

print("TITLE:", data["title"])
print("Saved narration.txt and video_package.json")

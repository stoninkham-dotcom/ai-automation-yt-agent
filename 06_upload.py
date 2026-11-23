import json
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

META_FILE = Path("output/meta/metadata.json")
THUMB_FILE = Path("output/thumbnails/thumbnail.jpg")

VIDEO_CANDIDATES = [
    Path("output/final_video.mp4"),
    Path("output/short.mp4"),
    Path("output/video.mp4"),
    Path("output/edited.mp4"),
]


def find_video_file() -> Path | None:
    for p in VIDEO_CANDIDATES:
        if p.exists() and p.stat().st_size > 0:
            return p
    output_dir = Path("output")
    if output_dir.exists():
        mp4s = sorted(
            [p for p in output_dir.rglob("*.mp4") if p.stat().st_size > 0],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if mp4s:
            return mp4s[0]
    return None


def get_youtube_service():
    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YT_REFRESH_TOKEN", "").strip()

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("Missing YT_CLIENT_ID, YT_CLIENT_SECRET, or YT_REFRESH_TOKEN.")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def load_metadata() -> dict:
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not parse metadata.json: {e}")
    return {}


def main():
    video_path = find_video_file()
    if not video_path:
        print("Error: No rendered .mp4 video found in output/.")
        sys.exit(1)

    meta = load_metadata()
    title = str(meta.get("title") or "Daily Focus Habit #Shorts").strip()[:100]
    description = str(meta.get("description") or "#Shorts").strip()
    hashtags = [
        (h if str(h).startswith("#") else f"#{h}")
        for h in meta.get("hashtags", [])
        if str(h).strip()
    ]
    if hashtags and not any(tag.lower() in description.lower() for tag in hashtags):
        description = f"{description}\n\n{' '.join(hashtags)}".strip()

    tags = [str(k).lstrip("#").strip() for k in meta.get("keywords", []) if str(k).strip()][:15]
    privacy_status = os.environ.get("YT_PRIVACY_STATUS", "public").strip() or "public"

    print(f"Uploading video: {video_path}")
    print(f"Title: {title}")

    youtube = get_youtube_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    print(f"Uploaded successfully! Video ID: {video_id}")
    print(f"Watch URL: https://www.youtube.com/shorts/{video_id}")

    thumb_path = Path(meta.get("thumbnail_path") or THUMB_FILE)
    if video_id and thumb_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
            ).execute()
            print(f"Thumbnail set from: {thumb_path}")
        except Exception as e:
            print(f"Warning: could not set custom thumbnail (normal if channel/Shorts restriction applies): {e}")


if __name__ == "__main__":
    main()
      

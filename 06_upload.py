import datetime
import json
import os
import sys
import time
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

THUMB_FILE = Path("output/thumbnails/thumbnail.jpg")


def get_today_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def find_video_file() -> Path | None:
    today = get_today_str()
    candidates = [
        Path("scripts") / today / "final_short.mp4",
        Path("scripts") / today / "final_video.mp4",
        Path("output/final_video.mp4"),
        Path("output/short.mp4"),
        Path("output/video.mp4"),
        Path("output/edited.mp4"),
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p

    for search_root in [Path("scripts"), Path("output")]:
        if search_root.exists():
            mp4s = sorted(
                [
                    p
                    for p in search_root.rglob("*.mp4")
                    if p.stat().st_size > 0 and "_edit_tmp" not in p.parts
                ],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if mp4s:
                return mp4s[0]
    return None


def find_metadata_file() -> Path | None:
    today = get_today_str()
    candidates = [
        Path("output/meta/metadata.json"),
        Path("scripts") / today / "metadata.json",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def get_youtube_service():
    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YT_REFRESH_TOKEN", "").strip()

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Missing YT_CLIENT_ID, YT_CLIENT_SECRET, or YT_REFRESH_TOKEN in environment."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise RuntimeError(
            f"YouTube OAuth refresh failed (invalid_grant / token issue): {e}. "
            "Generate a fresh YT_REFRESH_TOKEN and verify YT_CLIENT_ID / YT_CLIENT_SECRET."
        ) from e

    return build("youtube", "v3", credentials=creds)


def load_metadata() -> dict:
    meta_file = find_metadata_file()
    if meta_file and meta_file.exists():
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not parse {meta_file}: {e}")
    return {}


def upload_video_with_retry(youtube, body: dict, video_path: Path, max_retries: int = 3) -> str | None:
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)

    for attempt in range(1, max_retries + 1):
        try:
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"Upload progress: {int(status.progress() * 100)}%")

            video_id = response.get("id")
            if video_id:
                return video_id
            raise RuntimeError("Upload completed without returning a video ID.")
        except HttpError as e:
            status_code = getattr(e.resp, "status", None)
            retryable = status_code in (429, 500, 502, 503, 504)
            print(f"YouTube API HTTP error (attempt {attempt}/{max_retries}): {e}")
            if not retryable or attempt == max_retries:
                raise
        except Exception as e:
            print(f"Upload error (attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                raise

        sleep_seconds = attempt * 5
        print(f"Retrying upload in {sleep_seconds}s...")
        time.sleep(sleep_seconds)

    return None


def main():
    video_path = find_video_file()
    if not video_path:
        print("Error: No rendered .mp4 video found in scripts/ or output/.")
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

    try:
        youtube = get_youtube_service()
    except RuntimeError as e:
        print(f"Auth Error: {e}")
        sys.exit(1)

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

    try:
        video_id = upload_video_with_retry(youtube, body, video_path)
    except Exception as e:
        print(f"Upload failed: {e}")
        sys.exit(1)

    print(f"Uploaded successfully! Video ID: {video_id}")
    print(f"Watch URL: https://www.youtube.com/shorts/{video_id}")

    thumb_path = Path(meta.get("thumbnail_path") or THUMB_FILE)
    if video_id and thumb_path.exists():
        for attempt in range(1, 3):
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
                ).execute()
                print(f"Thumbnail set from: {thumb_path}")
                break
            except Exception as e:
                print(f"Warning: thumbnail attempt {attempt}/2 failed: {e}")
                if attempt < 2:
                    time.sleep(3)


if __name__ == "__main__":
    main()
    

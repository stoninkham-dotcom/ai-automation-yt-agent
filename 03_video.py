import datetime
import os
import urllib.parse
import urllib.request
import json

QUERIES = [
    "typing laptop office",
    "coding screen technology",
    "business meeting modern",
    "data analytics dashboard",
]

CLIPS_PER_QUERY = 2
MAX_CLIPS_TOTAL = 8


def get_today_folder() -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return os.path.join("scripts", now_utc.strftime("%Y-%m-%d"), "clips")


def fetch_pixabay_videos(api_key: str, query: str, per_page: int = 8) -> list:
    q = urllib.parse.quote(query)
    url = f"https://pixabay.com/api/videos/?key={api_key}&q={q}&per_page={per_page}&safesearch=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("hits", [])


def pick_best_mp4_url(hit: dict) -> str:
    videos = hit.get("videos", {})
    for quality in ("medium", "large", "small", "tiny"):
        info = videos.get(quality)
        if info and info.get("url"):
            return info["url"]
    return ""


def download_file(url: str, out_path: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        with open(out_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)


def main():
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("PIXABAY_API_KEY secret/env missing hai.")

    clips_dir = get_today_folder()
    os.makedirs(clips_dir, exist_ok=True)

    downloaded = 0
    seen_ids = set()

    for query in QUERIES:
        if downloaded >= MAX_CLIPS_TOTAL:
            break
        try:
            hits = fetch_pixabay_videos(api_key, query)
        except Exception as exc:
            print(f"Query '{query}' failed -> {exc}")
            continue

        added_for_query = 0
        for hit in hits:
            if downloaded >= MAX_CLIPS_TOTAL or added_for_query >= CLIPS_PER_QUERY:
                break
            vid_id = hit.get("id")
            if vid_id in seen_ids:
                continue
            mp4_url = pick_best_mp4_url(hit)
            if not mp4_url:
                continue

            out_file = os.path.join(clips_dir, f"clip_{downloaded + 1:02d}_{vid_id}.mp4")
            try:
                download_file(mp4_url, out_file)
                if os.path.exists(out_file) and os.path.getsize(out_file) > 10000:
                    seen_ids.add(vid_id)
                    downloaded += 1
                    added_for_query += 1
                    print(f"Saved {out_file}")
                else:
                    if os.path.exists(out_file):
                        os.remove(out_file)
            except Exception as exc:
                print(f"Download failed for id {vid_id} -> {exc}")

    if downloaded == 0:
        raise RuntimeError("Koi clip download nahi ho saki.")

    print(f"Total clips downloaded: {downloaded} in {clips_dir}")


if __name__ == "__main__":
    main()
  

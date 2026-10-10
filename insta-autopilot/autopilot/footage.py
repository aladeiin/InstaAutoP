from __future__ import annotations

import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

API = "https://api.pexels.com/videos/search"


def _best_file(video: dict) -> dict | None:
    """Pick a portrait mp4 that is sharp enough for 1080x1920 but not huge."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    portrait = [f for f in files if f["height"] >= f["width"]]
    pool = portrait or files
    if not pool:
        return None
    sharp = [f for f in pool if f["height"] >= 1280]
    if sharp:
        return min(sharp, key=lambda f: f["height"])
    return max(pool, key=lambda f: f["height"])


def fetch_clip(query: str, api_key: str, cache_dir: Path, used: set[int],
               min_seconds: float = 3.0) -> Path | None:
    """Download a stock clip for `query`. Returns None if nothing suitable is found
    (the renderer then uses a plain background, so the pipeline never stops)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(
            API,
            params={"query": query, "orientation": "portrait", "per_page": 15},
            headers={"Authorization": api_key},
            timeout=20,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
    except Exception as exc:
        log.warning("Pexels search failed for '%s': %s", query, exc)
        return None

    for v in videos:
        if v["id"] in used or v.get("duration", 0) < min_seconds:
            continue
        f = _best_file(v)
        if not f:
            continue
        dest = cache_dir / f"pexels_{v['id']}.mp4"
        if not dest.exists():
            try:
                with requests.get(f["link"], stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as out:
                        for part in resp.iter_content(chunk_size=1 << 20):
                            out.write(part)
            except Exception as exc:
                log.warning("Download failed for clip %s: %s", v["id"], exc)
                dest.unlink(missing_ok=True)
                continue
        used.add(v["id"])
        return dest
    log.info("No usable clip for '%s'", query)
    return None

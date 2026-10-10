from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class State:
    """Tiny JSON file that remembers what was posted, so the pipeline never
    double-posts on a day and never repeats a topic."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = {"entries": []}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
            self.data.setdefault("entries", [])

    @property
    def entries(self) -> list[dict]:
        return self.data["entries"]

    def posted_today(self, today: str) -> bool:
        return any(e["date"] == today and e.get("posted") for e in self.entries)

    def next_niche(self, rotation: list[str]) -> str:
        """Alternate through the rotation based on the last recorded post."""
        if not self.entries:
            return rotation[0]
        last = self.entries[-1]["niche"]
        if last not in rotation:
            return rotation[0]
        return rotation[(rotation.index(last) + 1) % len(rotation)]

    def recent_titles(self, niche: str, n: int = 40) -> list[str]:
        titles = [e["title"] for e in self.entries if e["niche"] == niche]
        return titles[-n:]

    def record(self, date: str, niche: str, title: str, media_id: str | None,
               posted: bool) -> None:
        self.entries.append(
            {"date": date, "niche": niche, "title": title,
             "media_id": media_id, "posted": posted}
        )
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

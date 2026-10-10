from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

UA = "insta-autopilot/1.0 (personal hobby project)"


def reddit_hints(subreddits: list[str], per_sub: int = 8, timeout: int = 10) -> list[str]:
    """Titles of today's top Reddit posts, used only as loose topic inspiration.

    Fails quietly: if Reddit blocks or times out, we just return fewer hints.
    """
    titles: list[str] = []
    for sub in subreddits:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"t": "day", "limit": per_sub},
                headers={"User-Agent": UA},
                timeout=timeout,
            )
            r.raise_for_status()
            for child in r.json()["data"]["children"]:
                t = child["data"].get("title", "").strip()
                if t and not child["data"].get("over_18"):
                    titles.append(t)
        except Exception as exc:  # network, JSON, rate limit: all non-fatal
            log.info("No trend hints from r/%s (%s)", sub, exc)
    return titles

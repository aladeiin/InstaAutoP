from __future__ import annotations

import logging
import time

import requests

from .config import env

log = logging.getLogger(__name__)


class InstagramError(RuntimeError):
    pass


class InstagramClient:
    """Publishes Reels through the official Instagram Graph API.

    Flow: create a media container from a public video URL -> wait until
    Instagram has processed it -> publish it.
    """

    def __init__(self, cfg: dict, user_id: str | None = None, token: str | None = None):
        ig = cfg["instagram"]
        self.base = f"{ig['graph_base'].rstrip('/')}/{ig['api_version']}"
        self.poll_seconds = ig["poll_seconds"]
        self.poll_timeout = ig["poll_timeout"]
        self.share_to_feed = ig.get("share_to_feed", True)
        self.user_id = user_id or env("IG_USER_ID")
        self.token = token or env("IG_ACCESS_TOKEN")

    # -- low level -------------------------------------------------------
    def _request(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        last_err = ""
        for attempt in range(3):
            try:
                r = requests.request(method, f"{self.base}/{path}",
                                     params=params if method == "GET" else None,
                                     data=params if method == "POST" else None,
                                     timeout=60)
            except requests.RequestException as exc:
                last_err = str(exc)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError:
                raise InstagramError(f"Unexpected reply (HTTP {r.status_code})")
            if r.status_code >= 400 or "error" in body:
                err = body.get("error", {})
                raise InstagramError(
                    f"Instagram API error {err.get('code', r.status_code)}: "
                    f"{err.get('message', 'unknown')}")
            return body
        raise InstagramError(f"Instagram API unreachable: {last_err}")

    # -- public ----------------------------------------------------------
    def check(self) -> str:
        """Return the Instagram username if the ID and token work."""
        body = self._request("GET", self.user_id, fields="username")
        return body.get("username", "(unknown)")

    def publish_reel(self, video_url: str, caption: str) -> str:
        body = self._request(
            "POST", f"{self.user_id}/media",
            media_type="REELS", video_url=video_url, caption=caption,
            share_to_feed=str(self.share_to_feed).lower())
        container = body["id"]
        log.info("Created media container %s", container)

        deadline = time.time() + self.poll_timeout
        while True:
            status = self._request("GET", container, fields="status_code,status")
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(
                    f"Instagram could not process the video ({code}): {status.get('status')}")
            if time.time() > deadline:
                raise InstagramError("Timed out waiting for Instagram to process the video")
            time.sleep(self.poll_seconds)

        published = self._request("POST", f"{self.user_id}/media_publish",
                                  creation_id=container)
        media_id = published["id"]
        log.info("Published Reel %s", media_id)
        return media_id

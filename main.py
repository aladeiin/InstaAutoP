"""Daily Instagram Reel pipeline.

    python main.py check              verify all keys and connections
    python main.py run --dry-run      make today's video but do not post
    python main.py run                make today's video and post it
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from autopilot import instagram, pipeline, scriptgen, storage, trends
from autopilot.config import ROOT, env, load_config
from autopilot.state import State

log = logging.getLogger("autopilot")


def setup_logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(ROOT / "logs" / "autopilot.log",
                                       maxBytes=1_000_000, backupCount=5,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console])


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "video"


def cmd_check(cfg: dict) -> int:
    ok = True

    def step(name: str, fn) -> None:
        nonlocal ok
        try:
            print(f"[ OK ] {name}: {fn()}")
        except Exception as exc:
            ok = False
            print(f"[FAIL] {name}: {exc}")

    def claude():
        import anthropic
        client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
        r = client.messages.create(model=cfg["claude"]["model"], max_tokens=20,
                                   messages=[{"role": "user", "content": "Say OK"}])
        return "connected"

    def pexels():
        import requests
        r = requests.get("https://api.pexels.com/videos/search",
                         params={"query": "city", "per_page": 1},
                         headers={"Authorization": env("PEXELS_API_KEY")}, timeout=20)
        r.raise_for_status()
        return "connected"

    def bucket():
        storage._client().head_bucket(Bucket=env("S3_BUCKET"))
        env("S3_PUBLIC_BASE_URL")
        return f"bucket '{env('S3_BUCKET')}' reachable"

    def ig():
        return "logged in as @" + instagram.InstagramClient(cfg).check()

    def voice():
        import tempfile, pathlib
        from autopilot import tts
        with tempfile.TemporaryDirectory() as d:
            _, dur = tts.synthesize("Testing the voice.", cfg["niches"][cfg["rotation"][0]]["voice"],
                                    "+0%", pathlib.Path(d) / "t.mp3")
        return f"speech works ({dur:.1f}s sample)"

    step("Claude API", claude)
    step("Voice (edge-tts)", voice)
    step("Pexels footage", pexels)
    step("Video hosting bucket", bucket)
    step("Instagram account", ig)
    return 0 if ok else 1


def cmd_run(cfg: dict, args) -> int:
    import anthropic

    state = State(ROOT / "state.json")
    today = datetime.now().date().isoformat()
    if state.posted_today(today) and not args.force and not args.dry_run:
        log.info("Already posted today (%s). Use --force to post again.", today)
        return 0

    niche = args.niche or state.next_niche(cfg["rotation"])
    if niche not in cfg["niches"]:
        log.error("Unknown niche '%s'. Choose from: %s", niche, ", ".join(cfg["niches"]))
        return 1
    niche_cfg = cfg["niches"][niche]
    log.info("Starting run for %s (niche: %s)%s", today, niche,
             " [dry run]" if args.dry_run else "")

    hints = []
    if cfg["trends"]["enabled"]:
        hints = trends.reddit_hints(niche_cfg.get("subreddits", []),
                                    cfg["trends"]["per_subreddit"])
    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    try:
        script = scriptgen.generate(client, cfg, niche, state.recent_titles(niche), hints)
    except scriptgen.ScriptRejected as exc:
        log.error("Skipping today, no script passed the checks: %s", exc)
        return 2

    outdir = ROOT / "output" / f"{today}_{niche}_{slugify(script['title'])}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    (outdir / "caption.txt").write_text(script["full_caption"], encoding="utf-8")

    video = pipeline.build_video(script, niche_cfg, cfg, outdir,
                                 env("PEXELS_API_KEY", required=False),
                                 ROOT / "cache" / "footage")
    log.info("Video ready: %s", video)

    if args.dry_run or not cfg["auto_post"]:
        log.info("Not posting (%s). Review the files in %s",
                 "dry run" if args.dry_run else "auto_post is false", outdir)
        return 0

    key = f"reels/{today}-{niche}-{slugify(script['title'])}.mp4"
    url = storage.upload_public(video, key)
    log.info("Uploaded video for Instagram to fetch")
    try:
        media_id = instagram.InstagramClient(cfg).publish_reel(url, script["full_caption"])
    finally:
        if cfg["storage"]["delete_after_publish"]:
            try:
                storage.delete(key)
            except Exception as exc:
                log.warning("Could not delete uploaded video: %s", exc)

    state.record(today, niche, script["title"], media_id, posted=True)
    log.info("Done. Posted '%s' (media id %s)", script["title"], media_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify keys and connections")
    run = sub.add_parser("run", help="generate (and post) today's Reel")
    run.add_argument("--niche", help="force a niche instead of alternating")
    run.add_argument("--dry-run", action="store_true",
                     help="make the video but do not upload or post")
    run.add_argument("--force", action="store_true",
                     help="post even if something was already posted today")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config()
    try:
        return cmd_check(cfg) if args.command == "check" else cmd_run(cfg, args)
    except Exception:
        log.exception("Run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

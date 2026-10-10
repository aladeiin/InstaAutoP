from __future__ import annotations

import logging
from pathlib import Path

from . import footage, render, tts

log = logging.getLogger(__name__)


def build_video(script: dict, niche_cfg: dict, cfg: dict, outdir: Path,
                pexels_key: str | None, cache_dir: Path) -> Path:
    """Turn a validated script into a finished vertical video file."""
    v = cfg["video"]
    work = outdir / "work"
    work.mkdir(parents=True, exist_ok=True)
    used: set[int] = set()
    scene_files: list[Path] = []
    scenes = script["scenes"]

    for i, scene in enumerate(scenes):
        audio = work / f"voice_{i:02d}.mp3"
        words, speech = tts.synthesize(scene["narration"], niche_cfg["voice"],
                                       niche_cfg.get("rate", "+0%"), audio)
        pause = v["end_pause"] if i == len(scenes) - 1 else v["scene_pause"]
        duration = speech + pause

        clip = None
        if pexels_key:
            clip = footage.fetch_clip(scene["visual"], pexels_key, cache_dir, used)
        captions = tts.chunk_words(words, per_chunk=v["caption_words"])
        log.info("Scene %d/%d: %.1fs, footage=%s", i + 1, len(scenes), duration,
                 clip.name if clip else "plain background")
        scene_files.append(render.render_scene(clip, audio, duration, captions,
                                               work, i, cfg))

    final = outdir / "video.mp4"
    render.concat_scenes(scene_files, final)
    return final

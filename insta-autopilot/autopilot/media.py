from __future__ import annotations

import re
import subprocess

import imageio_ffmpeg


def ffmpeg_exe() -> str:
    """Path to a bundled ffmpeg, so nothing needs installing system-wide."""
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-1500:]}")


def probe_duration(path) -> float:
    """Duration in seconds, read from ffmpeg's banner (no ffprobe needed)."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise RuntimeError(f"Could not read duration of {path}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    """Load config.yaml and the .env file next to it."""
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = ROOT
    return cfg


def env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Missing setting {name}. Add it to the .env file (see .env.example)."
        )
    return value

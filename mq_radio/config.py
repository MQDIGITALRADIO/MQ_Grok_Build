"""Paths and station defaults for M1.

Supports normal repo installs and frozen desktop builds (PyInstaller).
Writable data can be redirected with MQ_RADIO_DATA_DIR.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Repo root, or PyInstaller extract dir when frozen."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _default_data_dir(root: Path) -> Path:
    env = os.environ.get("MQ_RADIO_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # Desktop fallback if Electron did not set MQ_RADIO_DATA_DIR
        return Path.home() / "Library" / "Application Support" / "MQ Radio"
    return root / "data"


ROOT = _bundle_root()
DATA_DIR = _default_data_dir(ROOT)
DB_PATH = DATA_DIR / "mq_radio.db"

# Repo installs keep demo audio under fixtures/; packaged/desktop uses writable data dir.
if getattr(sys, "frozen", False) or os.environ.get("MQ_RADIO_DATA_DIR"):
    FIXTURES_DIR = DATA_DIR / "demo_audio"
else:
    FIXTURES_DIR = ROOT / "fixtures" / "demo_audio"

MIGRATIONS_DIR = ROOT / "migrations"

STATION_NAME = "MQ DIGITAL RADIO"
STATION_CALLSIGN = "MQ"

# Default MQ DIGITAL ruleset (seconds unless noted)
DEFAULT_RULES = {
    "artist_separation_minutes": 45,
    "title_separation_minutes": 90,
    "album_separation_minutes": 60,
    "same_artist_max_per_hour": 2,
    "explicit_allowed": False,
    "australian_content_min_pct": 25,
    "energy_daypart": {
        "morning": (5, 8),  # energy range 5-8
        "day": (4, 7),
        "afternoon": (5, 9),
        "evening": (3, 6),
        "overnight": (2, 5),
    },
}


def apply_data_dir(data_dir: Path | str) -> None:
    """Re-bind writable paths (used by desktop launcher)."""
    global DATA_DIR, DB_PATH, FIXTURES_DIR
    DATA_DIR = Path(data_dir)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = DATA_DIR / "mq_radio.db"
    FIXTURES_DIR = DATA_DIR / "demo_audio"

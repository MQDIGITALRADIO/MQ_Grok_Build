"""Paths and station defaults for M1."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mq_radio.db"
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

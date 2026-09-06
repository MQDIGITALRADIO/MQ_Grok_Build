"""Seed demo categories, clocks, rules, and synthetic audio fixtures."""

from __future__ import annotations

import array
import json
import math
import struct
import wave
from pathlib import Path
from typing import Optional

import mq_radio.config as _cfg
from mq_radio.db.connection import get_connection
from mq_radio.library.scanner import scan_directory


def _write_tone_wav(path: Path, duration_sec: float, freq: float = 440.0, volume: float = 0.2) -> int:
    """Write a short synthetic bed WAV (fundamental + harmonics + soft pad).

    Richer than a raw beep so desk timers / segue audition feel less toy-like,
    while staying small enough for fixtures. Uses array('h') for speed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 22050
    nframes = int(rate * duration_sec)
    samples = array.array("h")
    fade = min(0.08, duration_sec * 0.08)
    outro_fade = min(0.35, duration_sec * 0.12)
    two_pi = 2 * math.pi
    inv_rate = 1.0 / rate
    for i in range(nframes):
        t = i * inv_rate
        if t < fade:
            env = t / fade if fade else 1.0
        elif t > duration_sec - outro_fade:
            env = max(0.0, (duration_sec - t) / outro_fade) if outro_fade else 0.0
        else:
            env = 1.0
        pump = 0.92 + 0.08 * math.sin(two_pi * 0.35 * t)
        fund = math.sin(two_pi * freq * t)
        third = 0.28 * math.sin(two_pi * freq * 1.5 * t)
        fifth = 0.18 * math.sin(two_pi * freq * 2.0 * t)
        pad = 0.12 * math.sin(two_pi * (freq * 0.5) * t)
        shimmer = 0.04 * math.sin(two_pi * (freq * 3.7 + 17) * t + i * 0.001)
        mix = fund + third + fifth + pad + shimmer
        val = volume * env * pump * mix
        if val > 1.0:
            val = 1.0
        elif val < -1.0:
            val = -1.0
        samples.append(int(val * 32767))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return int(duration_sec * 1000)


def _write_local_demo_beds(data_dir: Optional[Path] = None) -> list[Path]:
    """Generate slightly longer beds under data/demo_beds/ (gitignored) for local desk feel."""
    root = Path(data_dir) if data_dir else _cfg.DATA_DIR
    out_dir = root / "demo_beds"
    out_dir.mkdir(parents=True, exist_ok=True)
    beds = [
        ("MQ_DEMO_Bed_A.wav", 28.0, 220.0, 0.18),
        ("MQ_DEMO_Bed_B.wav", 32.0, 277.0, 0.17),
        ("MQ_DEMO_ID_Sting.wav", 6.0, 880.0, 0.22),
        ("MQ_DEMO_Sweeper.wav", 5.0, 990.0, 0.2),
    ]
    written: list[Path] = []
    for name, dur, freq, vol in beds:
        p = out_dir / name
        # Skip rewrite when already present (keeps seed-demo / pytest snappy)
        if p.is_file() and p.stat().st_size > 1000:
            written.append(p)
            continue
        _write_tone_wav(p, dur, freq, vol)
        written.append(p)
    return written


DEMO_TRACKS = [
    # (filename, meta dict, duration, freq)
    ("Coastline Drift - Horizon Run.wav", {
        "artist": "Coastline Drift", "title": "Horizon Run", "album": "Tidal",
        "year": 2022, "genre": "Indie Pop", "bpm": 118, "energy": 6, "mood": "uplift",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 8000, "outro_ms": 12000, "isrc": "AU-MQ0-22-00001",
    }, 18.0, 440),
    ("Coastline Drift - Night Ferry.wav", {
        "artist": "Coastline Drift", "title": "Night Ferry", "album": "Tidal Nights",
        "year": 2022, "genre": "Indie Pop", "bpm": 102, "energy": 4, "mood": "chill",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Recurrent",
        "intro_ms": 5000, "outro_ms": 10000, "isrc": "AU-MQ0-22-00002",
    }, 16.0, 392),
    ("Sapphire Lane - Neon Tide.wav", {
        "artist": "Sapphire Lane", "title": "Neon Tide", "album": "Afterglow",
        "year": 2023, "genre": "Pop", "bpm": 124, "energy": 7, "mood": "bright",
        "gender": "F", "australian": True, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 6000, "outro_ms": 9000, "isrc": "AU-MQ0-23-00003",
    }, 17.0, 523),
    ("Sapphire Lane - Quiet Hours.wav", {
        "artist": "Sapphire Lane", "title": "Quiet Hours", "album": "Afterglow Soft",
        "year": 2023, "genre": "Pop", "bpm": 96, "energy": 3, "mood": "soft",
        "gender": "F", "australian": True, "era": "2020s", "rotation_category": "Gold",
        "intro_ms": 4000, "outro_ms": 8000, "isrc": "AU-MQ0-23-00004",
    }, 15.0, 349),
    ("Red Dirt Echo - Outback Static.wav", {
        "artist": "Red Dirt Echo", "title": "Outback Static", "album": "Dust",
        "year": 2021, "genre": "Alt Rock", "bpm": 130, "energy": 8, "mood": "drive",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 7000, "outro_ms": 11000, "isrc": "AU-MQ0-21-00005",
    }, 19.0, 277),
    ("Harbour Lights - Glass City.wav", {
        "artist": "Harbour Lights", "title": "Glass City", "album": "Skyline",
        "year": 2020, "genre": "Synth Pop", "bpm": 112, "energy": 5, "mood": "cool",
        "gender": "MIX", "australian": True, "era": "2020s", "rotation_category": "Recurrent",
        "intro_ms": 9000, "outro_ms": 10000, "isrc": "AU-MQ0-20-00006",
    }, 16.5, 466),
    ("Northern Relay - Paper Planes.wav", {
        "artist": "Northern Relay", "title": "Paper Planes", "album": "Signal",
        "year": 2019, "genre": "Indie", "bpm": 108, "energy": 5, "mood": "warm",
        "gender": "F", "australian": False, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 5000, "outro_ms": 9000, "isrc": "US-MQ0-19-00007",
    }, 14.0, 415),
    ("Northern Relay - Static Bloom.wav", {
        "artist": "Northern Relay", "title": "Static Bloom", "album": "Signal II",
        "year": 2019, "genre": "Indie", "bpm": 120, "energy": 6, "mood": "bright",
        "gender": "F", "australian": False, "era": "2010s", "rotation_category": "Recurrent",
        "intro_ms": 6000, "outro_ms": 8000, "isrc": "US-MQ0-19-00008",
    }, 15.5, 494),
    ("Volt Parade - Electric Weekend.wav", {
        "artist": "Volt Parade", "title": "Electric Weekend", "album": "Charge",
        "year": 2024, "genre": "Dance Pop", "bpm": 128, "energy": 9, "mood": "party",
        "gender": "MIX", "australian": False, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 4000, "outro_ms": 7000, "explicit": False, "isrc": "GB-MQ0-24-00009",
    }, 17.5, 554),
    ("Volt Parade - Midnight Grid.wav", {
        "artist": "Volt Parade", "title": "Midnight Grid", "album": "Charge Night",
        "year": 2024, "genre": "Dance Pop", "bpm": 122, "energy": 7, "mood": "night",
        "gender": "MIX", "australian": False, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 5000, "outro_ms": 9000, "isrc": "GB-MQ0-24-00010",
    }, 16.0, 370),
    ("Cedar & Stone - Long Drive Home.wav", {
        "artist": "Cedar & Stone", "title": "Long Drive Home", "album": "Miles",
        "year": 2018, "genre": "Folk Pop", "bpm": 92, "energy": 3, "mood": "reflective",
        "gender": "M", "australian": True, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 10000, "outro_ms": 14000, "isrc": "AU-MQ0-18-00011",
    }, 18.0, 330),
    ("Cedar & Stone - Sunday Market.wav", {
        "artist": "Cedar & Stone", "title": "Sunday Market", "album": "Miles Soft",
        "year": 2018, "genre": "Folk Pop", "bpm": 100, "energy": 4, "mood": "easy",
        "gender": "M", "australian": True, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 7000, "outro_ms": 11000, "isrc": "AU-MQ0-18-00012",
    }, 15.0, 294),
    ("Pixel Heart - Soft Reset.wav", {
        "artist": "Pixel Heart", "title": "Soft Reset", "album": "Boot",
        "year": 2023, "genre": "Electropop", "bpm": 116, "energy": 6, "mood": "playful",
        "gender": "F", "australian": False, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 5500, "outro_ms": 8500, "isrc": "US-MQ0-23-00013",
    }, 14.5, 587),
    ("Pixel Heart - Cache Miss.wav", {
        "artist": "Pixel Heart", "title": "Cache Miss", "album": "Boot Error",
        "year": 2023, "genre": "Electropop", "bpm": 126, "energy": 8, "mood": "up",
        "gender": "F", "australian": False, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 3500, "outro_ms": 6000, "isrc": "US-MQ0-23-00014",
    }, 13.5, 622),
    ("Coral State - Blue Room.wav", {
        "artist": "Coral State", "title": "Blue Room", "album": "Reef",
        "year": 2021, "genre": "R&B", "bpm": 88, "energy": 4, "mood": "smooth",
        "gender": "F", "australian": True, "era": "2020s", "rotation_category": "Recurrent",
        "intro_ms": 8000, "outro_ms": 12000, "isrc": "AU-MQ0-21-00015",
    }, 17.0, 311),
    ("Coral State - Heatwave.wav", {
        "artist": "Coral State", "title": "Heatwave", "album": "Reef Heat",
        "year": 2021, "genre": "R&B", "bpm": 104, "energy": 7, "mood": "summer",
        "gender": "F", "australian": True, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 4500, "outro_ms": 9000, "isrc": "AU-MQ0-21-00016",
    }, 16.0, 349),
    ("Iron Lantern - Last Call.wav", {
        "artist": "Iron Lantern", "title": "Last Call", "album": "Closing Time",
        "year": 2017, "genre": "Rock", "bpm": 136, "energy": 8, "mood": "raw",
        "gender": "M", "australian": False, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 3000, "outro_ms": 7000, "isrc": "US-MQ0-17-00017",
    }, 15.5, 196),
    ("Iron Lantern - Empty Booth.wav", {
        "artist": "Iron Lantern", "title": "Empty Booth", "album": "Closing Soft",
        "year": 2017, "genre": "Rock", "bpm": 110, "energy": 5, "mood": "moody",
        "gender": "M", "australian": False, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 6000, "outro_ms": 10000, "isrc": "US-MQ0-17-00018",
    }, 16.5, 220),
    ("Skyline Choir - Broadcast Dreams.wav", {
        "artist": "Skyline Choir", "title": "Broadcast Dreams", "album": "On Air",
        "year": 2022, "genre": "Pop Rock", "bpm": 114, "energy": 6, "mood": "hopeful",
        "gender": "MIX", "australian": True, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 7000, "outro_ms": 11000, "isrc": "AU-MQ0-22-00019",
    }, 18.5, 261),
    ("Skyline Choir - Sign Off.wav", {
        "artist": "Skyline Choir", "title": "Sign Off", "album": "On Air Late",
        "year": 2022, "genre": "Pop Rock", "bpm": 98, "energy": 3, "mood": "calm",
        "gender": "MIX", "australian": True, "era": "2020s", "rotation_category": "Gold",
        "intro_ms": 9000, "outro_ms": 13000, "isrc": "AU-MQ0-22-00020",
    }, 14.0, 247),

    ("Amber Circuit - Frequency.wav", {
        "artist": "Amber Circuit", "title": "Frequency", "album": "Freq",
        "year": 2024, "genre": "Indie", "bpm": 110, "energy": 5, "mood": "cool",
        "gender": "F", "australian": True, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 5000, "outro_ms": 8000, "isrc": "AU-MQ0-24-00021",
    }, 15.0, 400),
    ("Bridge & Beacon - Harbour Song.wav", {
        "artist": "Bridge & Beacon", "title": "Harbour Song", "album": "Pier",
        "year": 2020, "genre": "Folk", "bpm": 94, "energy": 4, "mood": "warm",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Gold",
        "intro_ms": 8000, "outro_ms": 10000, "isrc": "AU-MQ0-20-00022",
    }, 16.0, 360),
    ("Chrome Orchid - Laser Rain.wav", {
        "artist": "Chrome Orchid", "title": "Laser Rain", "album": "Orchid",
        "year": 2023, "genre": "Synth", "bpm": 125, "energy": 8, "mood": "bright",
        "gender": "MIX", "australian": False, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 4000, "outro_ms": 7000, "isrc": "US-MQ0-23-00023",
    }, 14.5, 510),
    ("Dune Pilot - Red Horizon.wav", {
        "artist": "Dune Pilot", "title": "Red Horizon", "album": "Dune",
        "year": 2021, "genre": "Alt", "bpm": 118, "energy": 6, "mood": "drive",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Recurrent",
        "intro_ms": 6000, "outro_ms": 9000, "isrc": "AU-MQ0-21-00024",
    }, 17.0, 280),
    ("Echo Market - Stall 12.wav", {
        "artist": "Echo Market", "title": "Stall 12", "album": "Market",
        "year": 2019, "genre": "Pop", "bpm": 105, "energy": 5, "mood": "easy",
        "gender": "F", "australian": False, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 7000, "outro_ms": 9000, "isrc": "GB-MQ0-19-00025",
    }, 15.5, 420),
    ("Far Station - Delay Line.wav", {
        "artist": "Far Station", "title": "Delay Line", "album": "Relay",
        "year": 2022, "genre": "Indie", "bpm": 112, "energy": 6, "mood": "night",
        "gender": "MIX", "australian": True, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 5500, "outro_ms": 8500, "isrc": "AU-MQ0-22-00026",
    }, 16.0, 390),
    ("Glass Orchard - Ripe.wav", {
        "artist": "Glass Orchard", "title": "Ripe", "album": "Orchard",
        "year": 2018, "genre": "Dream Pop", "bpm": 98, "energy": 3, "mood": "soft",
        "gender": "F", "australian": True, "era": "2010s", "rotation_category": "Gold",
        "intro_ms": 9000, "outro_ms": 12000, "isrc": "AU-MQ0-18-00027",
    }, 18.0, 340),
    ("High Voltage Tea - Kettle Whistle.wav", {
        "artist": "High Voltage Tea", "title": "Kettle Whistle", "album": "Brew",
        "year": 2024, "genre": "Dance", "bpm": 128, "energy": 9, "mood": "party",
        "gender": "MIX", "australian": False, "era": "2020s", "rotation_category": "Power",
        "intro_ms": 3000, "outro_ms": 6000, "isrc": "US-MQ0-24-00028",
    }, 13.0, 600),
    ("Ivory Road - Kilometres.wav", {
        "artist": "Ivory Road", "title": "Kilometres", "album": "Road",
        "year": 2020, "genre": "Rock", "bpm": 122, "energy": 7, "mood": "open",
        "gender": "M", "australian": True, "era": "2020s", "rotation_category": "Recurrent",
        "intro_ms": 5000, "outro_ms": 8000, "isrc": "AU-MQ0-20-00029",
    }, 16.5, 250),
    ("Juniper Fax - Cover Sheet.wav", {
        "artist": "Juniper Fax", "title": "Cover Sheet", "album": "Fax",
        "year": 2023, "genre": "Electropop", "bpm": 116, "energy": 6, "mood": "playful",
        "gender": "F", "australian": False, "era": "2020s", "rotation_category": "Current",
        "intro_ms": 4500, "outro_ms": 7500, "isrc": "US-MQ0-23-00030",
    }, 14.0, 470),

    # Production elements
    ("MQ_ID_Top.wav", {
        "artist": "MQ DIGITAL", "title": "MQ ID Top of Hour", "event_type": "ID",
        "rotation_category": "ID", "energy": 7, "australian": True,
    }, 4.0, 880),
    ("MQ_SWEEPER_01.wav", {
        "artist": "MQ DIGITAL", "title": "MQ Sweeper More Music", "event_type": "SWEEPER",
        "rotation_category": "SWEEPER", "energy": 7, "australian": True,
    }, 3.0, 990),
    ("MQ_PROMO_Weekend.wav", {
        "artist": "MQ DIGITAL", "title": "Weekend Promo", "event_type": "PROMO",
        "rotation_category": "PROMO", "energy": 6, "australian": True,
    }, 8.0, 660),
    ("MQ_BED_News.wav", {
        "artist": "MQ DIGITAL", "title": "News Bed", "event_type": "BED",
        "rotation_category": "BED", "energy": 4, "australian": True,
    }, 10.0, 180),
]


CATEGORIES = [
    ("A", "Power / Current A", "Highest rotation currents", 10, 1),
    ("B", "Recurrent B", "Recent recurrents", 20, 1),
    ("C", "Gold C", "Library gold", 30, 1),
    ("ID", "Station ID", "Legal / imaging IDs", 5, 0),
    ("SW", "Sweeper", "Imaging sweepers", 6, 0),
    ("PR", "Promo", "Promos", 7, 0),
    ("BED", "Bed", "Beds / underlays", 8, 0),
    ("VT", "Voice Track", "Voice tracks", 9, 0),
]


def _seed_categories(conn) -> None:
    for code, name, desc, pri, is_music in CATEGORIES:
        conn.execute(
            """INSERT OR IGNORE INTO categories (code, name, description, priority, is_music)
               VALUES (?,?,?,?,?)""",
            (code, name, desc, pri, is_music),
        )


def _seed_rules(conn) -> int:
    rules_json = json.dumps({
        "energy_daypart": {
            "morning": [5, 8],
            "day": [4, 7],
            "afternoon": [5, 9],
            "evening": [3, 6],
            "overnight": [2, 5],
        }
    })
    conn.execute(
        """INSERT OR REPLACE INTO station_rules (
            id, code, name, artist_separation_minutes, title_separation_minutes,
            album_separation_minutes, same_artist_max_per_hour, explicit_allowed,
            australian_content_min_pct, rules_json, active
        ) VALUES (1, 'MQ_DIGITAL', 'MQ DIGITAL Default Ruleset', 45, 90, 60, 2, 0, 25, ?, 1)""",
        (rules_json,),
    )
    return 1


def _seed_general_clock(conn) -> int:
    """Seed GENERAL + OVERNIGHT canonical clocks and daypart grid."""
    from mq_radio.scheduler.clocks import ensure_canonical_clocks

    ids = ensure_canonical_clocks(conn)
    return int(ids.get("GENERAL", 1))


def _seed_audio_fixtures() -> None:
    _cfg.FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for filename, meta, dur, freq in DEMO_TRACKS:
        wav_path = _cfg.FIXTURES_DIR / filename
        # Keep fixture durations lean for git; richer harmonic beds (same length).
        # Skip rewrite when present so pytest/seed stay fast; delete fixtures to regenerate.
        if wav_path.is_file() and wav_path.stat().st_size > 1000:
            duration_ms = int(dur * 1000)
        else:
            duration_ms = _write_tone_wav(wav_path, dur, freq)
        meta = dict(meta)
        meta["duration_ms"] = duration_ms
        side = wav_path.with_suffix(".json")
        side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Longer beds under data/demo_beds/ only (gitignored — not shipped in installer)
    try:
        _write_local_demo_beds()
    except Exception:
        pass


def _assign_categories_by_rotation(conn) -> None:
    mapping = {
        "Power": "A",
        "Current": "A",
        "Recurrent": "B",
        "Gold": "C",
        "ID": "ID",
        "SWEEPER": "SW",
        "PROMO": "PR",
        "BED": "BED",
    }
    for rot, code in mapping.items():
        cat = conn.execute("SELECT id FROM categories WHERE code = ?", (code,)).fetchone()
        if not cat:
            continue
        conn.execute(
            "UPDATE tracks SET category_id = ? WHERE rotation_category = ?",
            (cat["id"], rot),
        )


def seed_demo(db_path: Optional[Path] = None) -> dict:
    """Create fixtures, categories, GENERAL+OVERNIGHT clocks, MQ DIGITAL rules, scan library."""
    conn = get_connection(db_path)
    _seed_categories(conn)
    rules_id = _seed_rules(conn)
    clock_id = _seed_general_clock(conn)
    conn.commit()
    conn.close()

    _seed_audio_fixtures()
    scanned = scan_directory(_cfg.FIXTURES_DIR, db_path=db_path, category_code="A")

    conn = get_connection(db_path)
    _assign_categories_by_rotation(conn)
    conn.commit()
    track_count = conn.execute("SELECT COUNT(*) AS c FROM tracks").fetchone()["c"]
    conn.close()

    from mq_radio.scheduler.clocks import OVERNIGHT_HOURS, describe_daypart_grid

    return {
        "rules_id": rules_id,
        "clock_id": clock_id,
        "overnight_hours": sorted(OVERNIGHT_HOURS),
        "daypart_grid": describe_daypart_grid()["hour_clock"],
        "scanned": scanned,
        "tracks": track_count,
        "fixtures_dir": str(_cfg.FIXTURES_DIR),
    }

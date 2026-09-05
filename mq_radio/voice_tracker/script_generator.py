"""Template/rules AI announcer script generator (no live TTS yet).

Optional ``llm_hook`` can replace templates later; music selection stays
with the deterministic scheduler.
"""

from __future__ import annotations

import hashlib
import random
from typing import Callable, Optional

VARIATIONS = (
    "back_announce",
    "front_announce",
    "time_check",
    "station_promo",
    "silence",
)

STATION_DEFAULT = "MQ Digital"

# Rough spoken-word timing for placeholder log duration
_CHARS_PER_SEC = 14.0
_MIN_DURATION_MS = 4_000
_MAX_DURATION_MS = 18_000


def daypart_for_hour(hour: int) -> str:
    h = int(hour) % 24
    if 5 <= h < 10:
        return "morning"
    if 10 <= h < 15:
        return "day"
    if 15 <= h < 19:
        return "afternoon"
    if 19 <= h < 23:
        return "evening"
    return "overnight"


def estimate_duration_ms(script: str) -> int:
    text = (script or "").strip()
    if not text:
        return 0
    secs = max(len(text) / _CHARS_PER_SEC, _MIN_DURATION_MS / 1000)
    ms = int(secs * 1000)
    return min(max(ms, _MIN_DURATION_MS), _MAX_DURATION_MS)


def _stable_rng(*parts: object) -> random.Random:
    raw = "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def choose_variation(
    *,
    prev_track: Optional[dict],
    next_track: Optional[dict],
    daypart: str,
    rng: Optional[random.Random] = None,
    force: Optional[str] = None,
) -> str:
    """Pick a variation type from template rules (not live AI song pick)."""
    if force:
        if force not in VARIATIONS:
            raise ValueError(f"Unknown variation: {force}")
        return force

    r = rng or random.Random()
    roll = r.random()

    # Sometimes leave air silence between songs
    if daypart == "overnight" and roll < 0.28:
        return "silence"
    if roll < 0.12:
        return "silence"

    has_prev = bool(prev_track and (prev_track.get("title") or prev_track.get("artist")))
    has_next = bool(next_track and (next_track.get("title") or next_track.get("artist")))

    weights: list[tuple[str, float]] = []
    if has_prev:
        weights.append(("back_announce", 3.0 if daypart != "overnight" else 2.0))
    if has_next:
        weights.append(("front_announce", 2.5))
    weights.append(("time_check", 2.2 if daypart in ("morning", "overnight") else 1.0))
    weights.append(("station_promo", 1.8 if daypart in ("overnight", "evening") else 1.2))

    if not weights:
        return "silence"

    total = sum(w for _, w in weights)
    pick = r.random() * total
    upto = 0.0
    for name, w in weights:
        upto += w
        if pick <= upto:
            return name
    return weights[-1][0]


def _fmt_song(track: Optional[dict]) -> str:
    if not track:
        return ""
    title = (track.get("title") or "").strip()
    artist = (track.get("artist") or "").strip()
    if title and artist:
        return f"{title} by {artist}"
    return title or artist or "that last one"


def _templates(variation: str, prev: Optional[dict], nxt: Optional[dict],
               station: str, daypart: str, style: str) -> list[str]:
    prev_s = _fmt_song(prev)
    next_s = _fmt_song(nxt)
    warm = style in ("warm", "friendly", "casual")

    if variation == "silence":
        return [""]

    if variation == "back_announce":
        if warm:
            return [
                f"That was {prev_s} — you're locked into {station}.",
                f"And that one: {prev_s}. {station}, keeping it rolling.",
                f"{prev_s} right there on {station}.",
            ]
        return [
            f"That was {prev_s}. {station}.",
            f"{prev_s} — {station}.",
        ]

    if variation == "front_announce":
        if warm:
            return [
                f"Coming up next on {station}: {next_s}.",
                f"Here's {next_s} — on {station}.",
                f"Up next, {next_s}. Stay with {station}.",
            ]
        return [
            f"Next: {next_s}. {station}.",
            f"{next_s}, on {station}.",
        ]

    if variation == "time_check":
        if daypart == "overnight":
            return [
                f"You're overnight with {station} — music all the way through.",
                f"{station} overnight. More music coming right up.",
                f"Late night on {station}. Hang with us.",
            ]
        if daypart == "morning":
            return [
                f"Good morning — you're with {station}.",
                f"Morning vibes on {station}. Let's keep it moving.",
            ]
        if daypart == "afternoon":
            return [
                f"Drive time energy on {station}.",
                f"Afternoon on {station} — stick around.",
            ]
        return [
            f"You're listening to {station}.",
            f"{station} — right here, right now.",
        ]

    if variation == "station_promo":
        return [
            f"{station} — automated when you need it, live when you want it.",
            f"This is {station}. Jump in live anytime — AUTO holds the fort.",
            f"{station}: twenty-four seven playout. Your music, our clock.",
            f"You're on {station}. Voice tracks tonight, live when Matt jumps in.",
        ]

    return [f"{station}."]


def generate_script(
    *,
    prev_track: Optional[dict] = None,
    next_track: Optional[dict] = None,
    daypart: str = "day",
    station_name: str = STATION_DEFAULT,
    style: str = "warm",
    variation: Optional[str] = None,
    seed_key: Optional[str] = None,
    llm_hook: Optional[Callable[..., dict]] = None,
) -> dict:
    """
    Generate a short VT script.

    Returns dict with keys: variation, script, duration_ms, daypart, station_name, style, skipped.
    If variation is silence, script is empty and skipped=True.
    """
    if llm_hook is not None:
        return llm_hook(
            prev_track=prev_track,
            next_track=next_track,
            daypart=daypart,
            station_name=station_name,
            style=style,
            variation=variation,
        )

    rng = _stable_rng(
        seed_key,
        daypart,
        station_name,
        style,
        (prev_track or {}).get("title"),
        (prev_track or {}).get("artist"),
        (next_track or {}).get("title"),
        (next_track or {}).get("artist"),
        variation,
    )
    var = choose_variation(
        prev_track=prev_track,
        next_track=next_track,
        daypart=daypart,
        rng=rng,
        force=variation,
    )
    options = _templates(var, prev_track, next_track, station_name, daypart, style)
    script = options[rng.randrange(len(options))] if options else ""
    skipped = var == "silence" or not script.strip()
    return {
        "variation": var,
        "script": "" if skipped else script.strip(),
        "duration_ms": 0 if skipped else estimate_duration_ms(script),
        "daypart": daypart,
        "station_name": station_name,
        "style": style,
        "skipped": skipped,
        "source": "AI_TEMPLATE",
    }

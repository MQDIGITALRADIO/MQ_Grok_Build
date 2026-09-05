"""Separation and eligibility scoring for Living Log generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional


@dataclass
class Ruleset:
    artist_separation_minutes: int = 45
    title_separation_minutes: int = 90
    album_separation_minutes: int = 60
    same_artist_max_per_hour: int = 2
    explicit_allowed: bool = False
    australian_content_min_pct: int = 25
    energy_daypart: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any, rules_json: Optional[dict] = None) -> "Ruleset":
        energy = {}
        if rules_json and "energy_daypart" in rules_json:
            energy = rules_json["energy_daypart"]
        return cls(
            artist_separation_minutes=int(row["artist_separation_minutes"]),
            title_separation_minutes=int(row["title_separation_minutes"]),
            album_separation_minutes=int(row["album_separation_minutes"]),
            same_artist_max_per_hour=int(row["same_artist_max_per_hour"]),
            explicit_allowed=bool(row["explicit_allowed"]),
            australian_content_min_pct=int(row["australian_content_min_pct"]),
            energy_daypart=energy,
        )


def daypart_name(hour: int) -> str:
    if 5 <= hour < 10:
        return "morning"
    if 10 <= hour < 15:
        return "day"
    if 15 <= hour < 19:
        return "afternoon"
    if 19 <= hour < 23:
        return "evening"
    return "overnight"


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(value[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def minutes_since(then: Optional[datetime], now: datetime) -> Optional[float]:
    if then is None:
        return None
    return (now - then).total_seconds() / 60.0


@dataclass
class HistoryWindow:
    """Recent play history used for separation checks."""

    plays: list[dict] = field(default_factory=list)  # each: artist, title, album, played_at dt, track_id

    def add(self, track: dict, when: datetime) -> None:
        self.plays.append({
            "track_id": track["id"],
            "artist": (track["artist"] or "").strip().lower(),
            "title": (track["title"] or "").strip().lower(),
            "album": (track.get("album") or "").strip().lower(),
            "played_at": when,
        })

    def artist_count_in_hour(self, artist: str, when: datetime) -> int:
        key = artist.strip().lower()
        hour_start = when.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        return sum(
            1
            for p in self.plays
            if p["artist"] == key and hour_start <= p["played_at"] < hour_end
        )


def score_track(
    track: dict,
    when: datetime,
    history: HistoryWindow,
    rules: Ruleset,
    category_code: Optional[str] = None,
) -> tuple[float, list[str]]:
    """
    Score a candidate track for airtime `when`.
    Higher is better. Returns (score, reasons). Hard fails return (-inf-ish, reasons).
    """
    reasons: list[str] = []
    score = 100.0

    # Explicit
    if track.get("explicit") and not rules.explicit_allowed:
        return -1e9, ["explicit_blocked"]

    # Active / date window
    start = track.get("start_date")
    end = track.get("end_date")
    day = when.date().isoformat()
    if start and day < start:
        return -1e9, ["before_start_date"]
    if end and day > end:
        return -1e9, ["after_end_date"]

    artist = (track.get("artist") or "").strip().lower()
    title = (track.get("title") or "").strip().lower()
    album = (track.get("album") or "").strip().lower()

    # Artist separation
    for p in reversed(history.plays):
        if p["artist"] == artist:
            mins = minutes_since(p["played_at"], when)
            if mins is not None and mins < rules.artist_separation_minutes:
                return -1e9, [f"artist_sep<{rules.artist_separation_minutes}m"]
            if mins is not None:
                # reward more distance up to 2x separation
                score += min(mins / max(rules.artist_separation_minutes, 1), 2.0) * 5
            break

    # Title separation
    for p in reversed(history.plays):
        if p["title"] == title and p["artist"] == artist:
            mins = minutes_since(p["played_at"], when)
            if mins is not None and mins < rules.title_separation_minutes:
                return -1e9, [f"title_sep<{rules.title_separation_minutes}m"]
            break

    # Album separation
    if album:
        for p in reversed(history.plays):
            if p["album"] == album and p["artist"] == artist:
                mins = minutes_since(p["played_at"], when)
                if mins is not None and mins < rules.album_separation_minutes:
                    return -1e9, [f"album_sep<{rules.album_separation_minutes}m"]
                break

    # Same artist max per hour
    if history.artist_count_in_hour(artist, when) >= rules.same_artist_max_per_hour:
        return -1e9, ["artist_hour_cap"]

    # Last played — prefer resteds
    last = parse_dt(track.get("last_played"))
    if last:
        mins = minutes_since(last, when)
        if mins is not None:
            score += min(mins / 60.0, 48) * 0.5  # up to +24 for 48h rest
            reasons.append(f"rested_{int(mins)}m")
    else:
        score += 15  # never played bonus
        reasons.append("never_played")

    # Play count mild penalty (avoid overplay)
    pc = int(track.get("play_count") or 0)
    score -= min(pc, 50) * 0.1

    # Category match soft boost (caller already filtered hard)
    rot = (track.get("rotation_category") or "").lower()
    if category_code == "A" and rot in ("power", "current"):
        score += 10
    elif category_code == "B" and rot == "recurrent":
        score += 10
    elif category_code == "C" and rot == "gold":
        score += 10

    # Daypart energy
    dp = daypart_name(when.hour)
    energy_range = rules.energy_daypart.get(dp)
    energy = track.get("energy")
    if energy_range and energy is not None:
        lo, hi = energy_range[0], energy_range[1]
        if lo <= energy <= hi:
            score += 8
            reasons.append(f"energy_ok_{dp}")
        else:
            score -= abs(((lo + hi) / 2) - energy) * 2
            reasons.append(f"energy_off_{dp}")

    # Australian content soft preference (hard quota applied at hour aggregate by caller optionally)
    if track.get("australian"):
        score += 3
        reasons.append("australian")

    return score, reasons


def artist_separation_ok(
    artist: str,
    when: datetime,
    history: HistoryWindow,
    separation_minutes: int,
) -> bool:
    key = artist.strip().lower()
    for p in reversed(history.plays):
        if p["artist"] == key:
            mins = minutes_since(p["played_at"], when)
            if mins is not None and mins < separation_minutes:
                return False
            return True
    return True

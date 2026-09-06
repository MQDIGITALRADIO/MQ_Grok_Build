"""Canonical category clocks for deterministic Living Log expansion (M1).

Clocks are hour templates: ordered slots of event_type + category + timing/chain.
The scheduler expands clocks into the Living Log — AI never picks live music.

Daypart → clock mapping (default):
  overnight  23–04  → OVERNIGHT (extra VT placeholders, softer mix)
  morning    05–09  → GENERAL
  day        10–14  → GENERAL
  afternoon  15–18  → GENERAL
  evening    19–22  → GENERAL
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

# Hour ranges inclusive. Overnight wraps midnight.
DAYPART_HOURS: dict[str, tuple[int, ...]] = {
    "overnight": (23, 0, 1, 2, 3, 4),
    "morning": (5, 6, 7, 8, 9),
    "day": (10, 11, 12, 13, 14),
    "afternoon": (15, 16, 17, 18),
    "evening": (19, 20, 21, 22),
}

OVERNIGHT_HOURS: frozenset[int] = frozenset(DAYPART_HOURS["overnight"])


@dataclass(frozen=True)
class ClockSlotDef:
    position: int
    event_type: str
    category_code: Optional[str]
    timing_mode: str = "FLOAT"
    chain_mode: str = "AUTO"
    label: str = ""
    offset_sec: Optional[int] = None
    duration_sec: Optional[int] = None

    def as_tuple(self) -> tuple:
        return (
            self.position,
            self.event_type,
            self.category_code,
            self.timing_mode,
            self.chain_mode,
            self.label,
        )


@dataclass(frozen=True)
class ClockDef:
    code: str
    name: str
    description: str
    slots: tuple[ClockSlotDef, ...]
    duration_sec: int = 3600
    id_hint: Optional[int] = None  # preferred DB id for seed stability

    @property
    def vt_slot_count(self) -> int:
        return sum(1 for s in self.slots if s.event_type == "VOICE_TRACK")

    @property
    def music_slot_count(self) -> int:
        return sum(1 for s in self.slots if s.event_type == "MUSIC")

    def describe(self) -> dict[str, Any]:
        types: dict[str, int] = {}
        cats: dict[str, int] = {}
        for s in self.slots:
            types[s.event_type] = types.get(s.event_type, 0) + 1
            if s.category_code:
                cats[s.category_code] = cats.get(s.category_code, 0) + 1
        return {
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "duration_sec": self.duration_sec,
            "slot_count": len(self.slots),
            "vt_slots": self.vt_slot_count,
            "music_slots": self.music_slot_count,
            "event_type_counts": types,
            "category_counts": cats,
            "slots": [
                {
                    "position": s.position,
                    "event_type": s.event_type,
                    "category_code": s.category_code,
                    "timing_mode": s.timing_mode,
                    "chain_mode": s.chain_mode,
                    "label": s.label,
                    "offset_sec": s.offset_sec,
                    "duration_sec": s.duration_sec,
                }
                for s in self.slots
            ],
        }


def _slot(
    pos: int,
    et: str,
    cat: Optional[str],
    timing: str,
    chain: str,
    label: str,
    *,
    offset_sec: Optional[int] = None,
) -> ClockSlotDef:
    return ClockSlotDef(pos, et, cat, timing, chain, label, offset_sec=offset_sec)


# —— GENERAL: daytime / default hour ————————————————————————————————
GENERAL_SLOTS: tuple[ClockSlotDef, ...] = (
    _slot(0, "ID", "ID", "HIT", "AUTO", "Top of hour ID", offset_sec=0),
    _slot(1, "MUSIC", "A", "FLOAT", "MIX", "Power open"),
    _slot(2, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(3, "MUSIC", "A", "FLOAT", "MIX", "Power"),
    _slot(4, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "VT placeholder"),
    _slot(5, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(6, "PROMO", "PR", "SOFT", "AUTO", "Promo"),
    _slot(7, "MUSIC", "A", "FLOAT", "MIX", "Power"),
    _slot(8, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(9, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(10, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(11, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "VT placeholder"),
    _slot(12, "MUSIC", "A", "FLOAT", "MIX", "Power"),
    _slot(13, "ETM", None, "HIT", "HOLD", "ETM / stopset window"),
    _slot(14, "BREAK", None, "HARD", "MANUAL", "Stopset / break"),
    _slot(15, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(16, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(17, "MUSIC", "A", "FLOAT", "MIX", "Power"),
    _slot(18, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(19, "MUSIC", "A", "FLOAT", "MIX", "Power close"),
)

# —— OVERNIGHT: AI DJ path — more VT stubs, fewer promos, softer cats ——
# VT placeholders are filled later by generate-ai-breaks → approve path.
# Music mix leans B/C (recurrent/gold) with fewer A powers.
OVERNIGHT_SLOTS: tuple[ClockSlotDef, ...] = (
    _slot(0, "ID", "ID", "HIT", "AUTO", "Overnight top ID", offset_sec=0),
    _slot(1, "MUSIC", "B", "FLOAT", "MIX", "Overnight open"),
    _slot(2, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "Overnight VT"),
    _slot(3, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(4, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(5, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(6, "MUSIC", "A", "FLOAT", "MIX", "Power (sparse)"),
    _slot(7, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "Overnight VT"),
    _slot(8, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(9, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(10, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(11, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(12, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "Overnight VT"),
    _slot(13, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(14, "ETM", None, "HIT", "HOLD", "ETM / stopset window"),
    _slot(15, "BREAK", None, "HARD", "MANUAL", "Stopset / break"),
    _slot(16, "MUSIC", "C", "FLOAT", "MIX", "Gold"),
    _slot(17, "VOICE_TRACK", "VT", "FLOAT", "AUTO", "Overnight VT"),
    _slot(18, "MUSIC", "B", "FLOAT", "MIX", "Recurrent"),
    _slot(19, "SWEEPER", "SW", "FLOAT", "AUTO", "Sweeper"),
    _slot(20, "MUSIC", "A", "FLOAT", "MIX", "Power (sparse)"),
    _slot(21, "MUSIC", "C", "FLOAT", "MIX", "Gold close"),
)

GENERAL_CLOCK = ClockDef(
    code="GENERAL",
    name="General Hour",
    description="Default MQ DIGITAL hour clock (day / drive / evening)",
    slots=GENERAL_SLOTS,
    id_hint=1,
)

OVERNIGHT_CLOCK = ClockDef(
    code="OVERNIGHT",
    name="Overnight / AI DJ Hour",
    description=(
        "Overnight clock with extra VOICE_TRACK placeholders for AI announcer "
        "scripts; softer category mix. Music still selected by the deterministic "
        "scheduler — AI only fills VT scripts after the log is committed."
    ),
    slots=OVERNIGHT_SLOTS,
    id_hint=2,
)

CANONICAL_CLOCKS: tuple[ClockDef, ...] = (GENERAL_CLOCK, OVERNIGHT_CLOCK)

# Default hour → clock code (overridable via daypart_clocks table after seed)
DEFAULT_HOUR_CLOCK: dict[int, str] = {
    **{h: "OVERNIGHT" for h in OVERNIGHT_HOURS},
    **{h: "GENERAL" for h in range(24) if h not in OVERNIGHT_HOURS},
}


def daypart_for_hour(hour: int) -> str:
    h = int(hour) % 24
    for name, hours in DAYPART_HOURS.items():
        if h in hours:
            return name
    return "overnight"


def clock_code_for_hour(hour: int, mapping: Optional[dict[int, str]] = None) -> str:
    m = mapping or DEFAULT_HOUR_CLOCK
    return m.get(int(hour) % 24, "GENERAL")


def get_clock_def(code: str) -> ClockDef:
    for c in CANONICAL_CLOCKS:
        if c.code == code:
            return c
    raise KeyError(f"Unknown clock code: {code}")


def list_clock_defs() -> list[dict[str, Any]]:
    return [c.describe() for c in CANONICAL_CLOCKS]


def describe_daypart_grid() -> dict[str, Any]:
    return {
        "dayparts": {k: list(v) for k, v in DAYPART_HOURS.items()},
        "hour_clock": {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)},
        "clocks": list_clock_defs(),
        "notes": [
            "Living Log generation expands daypart_clocks → clock_slots.",
            "AI never selects MUSIC live; VT scripts are a post-commit path.",
            "MANUAL log rows survive regenerate unless --force.",
        ],
    }


def ensure_canonical_clocks(conn) -> dict[str, int]:
    """Upsert GENERAL + OVERNIGHT clocks, slots, and default daypart_clocks.

    Returns {code: clock_id}. Idempotent for demo seed / migrate-forward.
    """
    ids: dict[str, int] = {}
    for clock in CANONICAL_CLOCKS:
        row = conn.execute(
            "SELECT id FROM clocks WHERE code = ?", (clock.code,)
        ).fetchone()
        if row:
            clock_id = int(row["id"])
            conn.execute(
                """UPDATE clocks SET name=?, description=?, duration_sec=? WHERE id=?""",
                (clock.name, clock.description, clock.duration_sec, clock_id),
            )
        else:
            if clock.id_hint is not None:
                # Prefer stable ids when free
                taken = conn.execute(
                    "SELECT 1 FROM clocks WHERE id = ?", (clock.id_hint,)
                ).fetchone()
                if not taken:
                    conn.execute(
                        """INSERT INTO clocks (id, code, name, description, duration_sec)
                           VALUES (?,?,?,?,?)""",
                        (
                            clock.id_hint,
                            clock.code,
                            clock.name,
                            clock.description,
                            clock.duration_sec,
                        ),
                    )
                    clock_id = clock.id_hint
                else:
                    cur = conn.execute(
                        """INSERT INTO clocks (code, name, description, duration_sec)
                           VALUES (?,?,?,?)""",
                        (clock.code, clock.name, clock.description, clock.duration_sec),
                    )
                    clock_id = int(cur.lastrowid)
            else:
                cur = conn.execute(
                    """INSERT INTO clocks (code, name, description, duration_sec)
                       VALUES (?,?,?,?)""",
                    (clock.code, clock.name, clock.description, clock.duration_sec),
                )
                clock_id = int(cur.lastrowid)
        ids[clock.code] = clock_id

        conn.execute("DELETE FROM clock_slots WHERE clock_id = ?", (clock_id,))
        for s in clock.slots:
            conn.execute(
                """INSERT INTO clock_slots
                   (clock_id, position, event_type, category_code, timing_mode,
                    chain_mode, label, offset_sec, duration_sec)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    clock_id,
                    s.position,
                    s.event_type,
                    s.category_code,
                    s.timing_mode,
                    s.chain_mode,
                    s.label,
                    s.offset_sec,
                    s.duration_sec,
                ),
            )

    conn.execute("DELETE FROM daypart_clocks")
    for hour in range(24):
        code = DEFAULT_HOUR_CLOCK[hour]
        conn.execute(
            "INSERT INTO daypart_clocks (hour, clock_id, day_mask) VALUES (?, ?, 127)",
            (hour, ids[code]),
        )
    return ids


def load_hour_clock_map(conn) -> dict[int, int]:
    """hour → clock_id from daypart_clocks (falls back to GENERAL / id 1)."""
    hour_clocks: dict[int, int] = {}
    for row in conn.execute("SELECT hour, clock_id FROM daypart_clocks").fetchall():
        hour_clocks[int(row["hour"])] = int(row["clock_id"])
    if not hour_clocks:
        row = conn.execute(
            "SELECT id FROM clocks WHERE code='GENERAL' ORDER BY id LIMIT 1"
        ).fetchone()
        default_id = int(row["id"]) if row else 1
        for h in range(24):
            hour_clocks[h] = default_id
    return hour_clocks


def normalize_hours(hours: Optional[Iterable[int]]) -> Optional[list[int]]:
    """None → full day. Else unique sorted hours in 0..23."""
    if hours is None:
        return None
    out = sorted({int(h) % 24 for h in hours})
    if not out:
        return None
    return out

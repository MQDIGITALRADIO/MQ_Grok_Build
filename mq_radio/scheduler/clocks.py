"""Canonical category clocks for deterministic Living Log expansion (M1).

Clocks are hour templates: ordered slots of event_type + category + timing/chain.
The scheduler expands clocks into the Living Log — AI never picks live music.

Daypart → clock mapping (default, overridable in Daypart Designer):
  overnight  23–04  → OVERNIGHT (extra VT placeholders, softer mix)
  morning    05–09  → GENERAL
  day        10–14  → GENERAL
  afternoon  15–18  → GENERAL
  evening    19–22  → GENERAL
Operator may assign any named clock (incl. clones) per hour 0–23.
Day masks (Sun=1 … Sat=64) allow weekday vs weekend (or per-day) grids;
generate_log resolves the map for the log date's weekday.
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

# day_mask bits: Sun=1, Mon=2, Tue=4, Wed=8, Thu=16, Fri=32, Sat=64 (schema)
DAY_MASK_ALL = 127
DAY_MASK_WEEKDAY = 62  # Mon–Fri
DAY_MASK_WEEKEND = 65  # Sat+Sun
DAY_MASK_BITS: dict[str, int] = {
    "sun": 1,
    "mon": 2,
    "tue": 4,
    "wed": 8,
    "thu": 16,
    "fri": 32,
    "sat": 64,
}
DAY_MASK_PACKS: dict[str, int] = {
    "all": DAY_MASK_ALL,
    "weekday": DAY_MASK_WEEKDAY,
    "weekend": DAY_MASK_WEEKEND,
    **DAY_MASK_BITS,
}
PACK_LABELS: dict[str, str] = {
    "all": "All days",
    "weekday": "Weekday (Mon–Fri)",
    "weekend": "Weekend (Sat–Sun)",
    "sun": "Sunday",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
}


def day_mask_bit_count(mask: int) -> int:
    return bin(int(mask) & 0x7F).count("1")


def weekday_bit_for_date(log_date: str | Any) -> int:
    """Return schema day_mask bit for a YYYY-MM-DD date (Sun=1 … Sat=64)."""
    from datetime import date, datetime

    if hasattr(log_date, "weekday") and callable(getattr(log_date, "weekday")):
        d = log_date  # date/datetime
    else:
        s = str(log_date).strip()[:10]
        d = datetime.strptime(s, "%Y-%m-%d").date()
    # Python weekday: Mon=0 … Sun=6 → schema index Sun=0 … Sat=6
    schema_idx = (int(d.weekday()) + 1) % 7
    return 1 << schema_idx


def resolve_pack_name(pack_or_mask: Any) -> tuple[str, int]:
    """Normalize pack name or int mask → (pack_key, mask). Default all/127."""
    if pack_or_mask is None or pack_or_mask == "":
        return "all", DAY_MASK_ALL
    if isinstance(pack_or_mask, int) or (isinstance(pack_or_mask, str) and str(pack_or_mask).isdigit()):
        mask = int(pack_or_mask) & 0x7F
        if mask <= 0:
            mask = DAY_MASK_ALL
        for name, m in DAY_MASK_PACKS.items():
            if m == mask:
                return name, mask
        return f"mask_{mask}", mask
    key = str(pack_or_mask).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "weekdays": "weekday",
        "week_day": "weekday",
        "week_end": "weekend",
        "all_days": "all",
        "default": "all",
        "sunday": "sun",
        "monday": "mon",
        "tuesday": "tue",
        "wednesday": "wed",
        "thursday": "thu",
        "friday": "fri",
        "saturday": "sat",
    }
    key = aliases.get(key, key)
    if key not in DAY_MASK_PACKS:
        raise ValueError(f"unknown daypart pack: {pack_or_mask}")
    return key, DAY_MASK_PACKS[key]


def default_hour_clock_codes() -> dict[str, str]:
    return {str(h): DEFAULT_HOUR_CLOCK[h] for h in range(24)}


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


def ensure_canonical_clocks(conn, *, reset: bool = False) -> dict[str, int]:
    """Upsert GENERAL + OVERNIGHT clocks, slots, and default daypart_clocks.

    Returns {code: clock_id}.

    - Default (reset=False): create missing clocks/slots only — **preserve**
      operator edits from the Clock Editor.
    - reset=True: rewrite slots + daypart grid from CANONICAL_CLOCKS (seed / Reset).
    """
    ids: dict[str, int] = {}
    for clock in CANONICAL_CLOCKS:
        row = conn.execute(
            "SELECT id FROM clocks WHERE code = ?", (clock.code,)
        ).fetchone()
        created = False
        if row:
            clock_id = int(row["id"])
            if reset:
                conn.execute(
                    """UPDATE clocks SET name=?, description=?, duration_sec=? WHERE id=?""",
                    (clock.name, clock.description, clock.duration_sec, clock_id),
                )
        else:
            created = True
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

        slot_count = conn.execute(
            "SELECT COUNT(*) AS c FROM clock_slots WHERE clock_id = ?", (clock_id,)
        ).fetchone()["c"]
        if reset or created or int(slot_count) == 0:
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

    daypart_n = conn.execute("SELECT COUNT(*) AS c FROM daypart_clocks").fetchone()["c"]
    if reset or int(daypart_n) == 0:
        conn.execute("DELETE FROM daypart_clocks")
        for hour in range(24):
            code = DEFAULT_HOUR_CLOCK[hour]
            conn.execute(
                "INSERT INTO daypart_clocks (hour, clock_id, day_mask) VALUES (?, ?, 127)",
                (hour, ids[code]),
            )
    return ids


def _clock_code_ids(conn) -> dict[str, int]:
    return {str(row["code"]): int(row["id"]) for row in conn.execute("SELECT id, code FROM clocks")}


def _fallback_clock_id(code_ids: dict[str, int], hour: int) -> int:
    general_id = code_ids.get("GENERAL")
    overnight_id = code_ids.get("OVERNIGHT", general_id)
    if general_id is None:
        general_id = overnight_id or 1
    code = DEFAULT_HOUR_CLOCK.get(hour, "GENERAL")
    if code == "OVERNIGHT" and overnight_id is not None:
        return overnight_id
    return code_ids.get(code, general_id)


def load_hour_clock_map(conn, log_date: Optional[Any] = None) -> dict[int, int]:
    """hour → clock_id from daypart_clocks for a calendar date's weekday.

    Rows may carry day_mask packs (ALL=127, WEEKDAY=62, WEEKEND=65, or
    single-day bits). For the log date, the narrowest matching mask wins.
    Missing hours fall back to DEFAULT_HOUR_CLOCK (OVERNIGHT 23–04).
    If log_date is None, prefer ALL (127) rows, else any row (legacy).
    """
    code_ids = _clock_code_ids(conn)
    bit: Optional[int] = None
    if log_date is not None:
        bit = weekday_bit_for_date(log_date)

    by_hour: dict[int, list[tuple[int, int]]] = {h: [] for h in range(24)}
    for row in conn.execute(
        "SELECT hour, clock_id, day_mask FROM daypart_clocks"
    ).fetchall():
        h = int(row["hour"])
        if h < 0 or h > 23:
            continue
        mask = int(row["day_mask"] if row["day_mask"] is not None else DAY_MASK_ALL) & 0x7F
        if mask <= 0:
            mask = DAY_MASK_ALL
        by_hour[h].append((mask, int(row["clock_id"])))

    hour_clocks: dict[int, int] = {}
    for h in range(24):
        candidates = by_hour[h]
        chosen: Optional[int] = None
        if bit is not None:
            matching = [(m, cid) for m, cid in candidates if (m & bit)]
            if matching:
                matching.sort(key=lambda t: (day_mask_bit_count(t[0]), t[0]))
                chosen = matching[0][1]
        else:
            # No date: prefer exact ALL pack, else first row
            all_rows = [cid for m, cid in candidates if m == DAY_MASK_ALL]
            if all_rows:
                chosen = all_rows[0]
            elif candidates:
                candidates.sort(key=lambda t: (day_mask_bit_count(t[0]), t[0]))
                chosen = candidates[0][1]
        if chosen is None:
            chosen = _fallback_clock_id(code_ids, h)
        hour_clocks[h] = chosen
    return hour_clocks


def normalize_hours(hours: Optional[Iterable[int]]) -> Optional[list[int]]:
    """None → full day. Else unique sorted hours in 0..23."""
    if hours is None:
        return None
    out = sorted({int(h) % 24 for h in hours})
    if not out:
        return None
    return out


# —— Clock editor: load / save DB + JSON mirror ——————————————————————


EVENT_TYPES_EDITABLE = (
    "MUSIC",
    "ID",
    "SWEEPER",
    "PROMO",
    "VOICE_TRACK",
    "ETM",
    "BREAK",
    "FILLER",
    "BED",
    "COMMAND",
    "LIVE",
    "SHOW",
)
TIMING_MODES = ("FLOAT", "HIT", "HARD", "SOFT")
CHAIN_MODES = ("AUTO", "MIX", "SEQ", "CUT", "HOLD", "MANUAL")


def load_clocks_from_db(conn) -> list[dict[str, Any]]:
    """Load all clocks + slots from DB (editor / API source of truth)."""
    clocks = []
    for row in conn.execute(
        "SELECT id, code, name, description, duration_sec FROM clocks ORDER BY id"
    ).fetchall():
        slots = conn.execute(
            """SELECT id, position, event_type, category_code, timing_mode, chain_mode,
                      label, offset_sec, duration_sec
               FROM clock_slots WHERE clock_id=? ORDER BY position""",
            (row["id"],),
        ).fetchall()
        clocks.append(
            {
                "id": int(row["id"]),
                "code": row["code"],
                "name": row["name"],
                "description": row["description"],
                "duration_sec": int(row["duration_sec"] or 3600),
                "slots": [
                    {
                        "id": int(s["id"]),
                        "position": int(s["position"]),
                        "event_type": s["event_type"],
                        "category_code": s["category_code"],
                        "timing_mode": s["timing_mode"] or "FLOAT",
                        "chain_mode": s["chain_mode"] or "AUTO",
                        "label": s["label"] or "",
                        "offset_sec": s["offset_sec"],
                        "duration_sec": s["duration_sec"],
                    }
                    for s in slots
                ],
            }
        )
    return clocks


def load_daypart_grid_from_db(
    conn, day_mask: int = DAY_MASK_ALL, *, inherit: bool = True
) -> dict[str, str]:
    """hour(str) → clock code for one day_mask pack.

    If inherit and the pack has no rows, fall back to ALL (127) then defaults.
    """
    mask = int(day_mask) & 0x7F
    if mask <= 0:
        mask = DAY_MASK_ALL
    out: dict[str, str] = {}
    rows = conn.execute(
        """SELECT d.hour, c.code FROM daypart_clocks d
           JOIN clocks c ON c.id = d.clock_id
           WHERE d.day_mask = ? ORDER BY d.hour""",
        (mask,),
    ).fetchall()
    for r in rows:
        out[str(int(r["hour"]))] = r["code"]
    if len(out) == 24:
        return out
    if inherit and mask != DAY_MASK_ALL:
        base = load_daypart_grid_from_db(conn, DAY_MASK_ALL, inherit=False)
        for h in range(24):
            key = str(h)
            if key not in out:
                out[key] = base.get(key, DEFAULT_HOUR_CLOCK[h])
        return out
    if not out:
        return default_hour_clock_codes()
    # Partial pack: fill holes from defaults
    for h in range(24):
        key = str(h)
        if key not in out:
            out[key] = DEFAULT_HOUR_CLOCK[h]
    return out


def load_daypart_packs(conn) -> dict[str, Any]:
    """Named day_mask packs present in DB (+ inherited previews for editor)."""
    present_masks = {
        int(r["day_mask"])
        for r in conn.execute("SELECT DISTINCT day_mask FROM daypart_clocks").fetchall()
    }
    packs: dict[str, Any] = {}
    for name, mask in (("all", DAY_MASK_ALL), ("weekday", DAY_MASK_WEEKDAY), ("weekend", DAY_MASK_WEEKEND)):
        stored = mask in present_masks
        packs[name] = {
            "mask": mask,
            "label": PACK_LABELS[name],
            "stored": stored or (name == "all" and not present_masks),
            "hour_clock": load_daypart_grid_from_db(conn, mask, inherit=True),
        }
    # Optional single-day packs when present
    days: dict[str, Any] = {}
    for name, mask in DAY_MASK_BITS.items():
        if mask in present_masks:
            days[name] = {
                "mask": mask,
                "label": PACK_LABELS[name],
                "stored": True,
                "hour_clock": load_daypart_grid_from_db(conn, mask, inherit=True),
            }
    return {"packs": packs, "days": days, "masks": dict(DAY_MASK_PACKS)}


def clocks_bundle(conn) -> dict[str, Any]:
    """Full editor payload: clocks, daypart grid / packs, canonical notes."""
    clocks = load_clocks_from_db(conn)
    packs_info = load_daypart_packs(conn)
    hour_clock = packs_info["packs"]["all"]["hour_clock"]
    return {
        "clocks": clocks,
        "hour_clock": hour_clock,
        "daypart_packs": packs_info["packs"],
        "daypart_days": packs_info["days"],
        "day_masks": packs_info["masks"],
        "dayparts": {k: list(v) for k, v in DAYPART_HOURS.items()},
        "event_types": list(EVENT_TYPES_EDITABLE),
        "timing_modes": list(TIMING_MODES),
        "chain_modes": list(CHAIN_MODES),
        "notes": [
            "Edits save to SQLite clock_slots; mirrored to data/clocks.json.",
            "Daypart Designer: hour 0–23 → clock via daypart_clocks + day_mask packs (All / Weekday / Weekend).",
            "generate-log uses the log date weekday: narrowest matching day_mask wins (fallback GENERAL/OVERNIGHT 23–04).",
            "Clone GENERAL/OVERNIGHT (or any clock) to create named clocks for the grid.",
            "ETM / HIT / HARD slots are hard markers; FLOAT content fills toward them.",
            "MANUAL Living Log rows survive regenerate unless --force.",
        ],
    }


def _normalize_slot_payload(raw: dict, position: int) -> dict[str, Any]:
    et = str(raw.get("event_type") or "MUSIC").strip().upper()
    if et in ("VT", "VOICE TRACK"):
        et = "VOICE_TRACK"
    if et not in EVENT_TYPES_EDITABLE:
        et = "MUSIC"
    timing = str(raw.get("timing_mode") or "FLOAT").strip().upper()
    if timing not in TIMING_MODES:
        timing = "FLOAT"
    chain = str(raw.get("chain_mode") or "AUTO").strip().upper()
    # Enum uses CUT; editor historically offered SEQ — accept both
    if chain not in CHAIN_MODES:
        chain = "AUTO"
    cat = raw.get("category_code")
    if cat is not None:
        cat = str(cat).strip() or None
    offset = raw.get("offset_sec")
    if offset is not None and offset != "":
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = None
    else:
        offset = None
    dur = raw.get("duration_sec")
    if dur is not None and dur != "":
        try:
            dur = int(dur)
        except (TypeError, ValueError):
            dur = None
    else:
        dur = None
    label = str(raw.get("label") or "").strip()
    # ETM defaults
    if et == "ETM":
        timing = "HIT"
        if not label:
            label = "ETM / stopset window"
    if et == "VOICE_TRACK" and not cat:
        cat = "VT"
    return {
        "position": int(position),
        "event_type": et,
        "category_code": cat,
        "timing_mode": timing,
        "chain_mode": chain,
        "label": label,
        "offset_sec": offset,
        "duration_sec": dur,
    }


def save_clock_slots(
    conn,
    code: str,
    slots: list[dict],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Replace clock_slots for an existing clock code. Returns saved clock dict."""
    row = conn.execute("SELECT * FROM clocks WHERE code = ?", (code,)).fetchone()
    if not row:
        raise KeyError(f"Unknown clock code: {code}")
    clock_id = int(row["id"])
    if name is not None:
        conn.execute("UPDATE clocks SET name=? WHERE id=?", (str(name), clock_id))
    if description is not None:
        conn.execute(
            "UPDATE clocks SET description=? WHERE id=?", (str(description), clock_id)
        )

    normalized = [_normalize_slot_payload(s, i) for i, s in enumerate(slots or [])]
    conn.execute("DELETE FROM clock_slots WHERE clock_id = ?", (clock_id,))
    for s in normalized:
        conn.execute(
            """INSERT INTO clock_slots
               (clock_id, position, event_type, category_code, timing_mode,
                chain_mode, label, offset_sec, duration_sec)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                clock_id,
                s["position"],
                s["event_type"],
                s["category_code"],
                s["timing_mode"],
                s["chain_mode"],
                s["label"],
                s["offset_sec"],
                s["duration_sec"],
            ),
        )
    saved = load_clocks_from_db(conn)
    for c in saved:
        if c["code"] == code:
            return c
    raise RuntimeError("save_clock_slots: clock missing after write")


def save_daypart_grid(
    conn,
    hour_clock: dict,
    *,
    day_mask: int = DAY_MASK_ALL,
    pack: Optional[str] = None,
    replace_all_packs: bool = False,
) -> dict[str, str]:
    """Update daypart_clocks for one day_mask pack from {hour: code}.

    - Default pack is ALL (127). Other packs (weekday=62, weekend=65, …) are
      written without wiping sibling packs unless replace_all_packs=True
      (Defaults / full reset).
    - Returns the saved pack's hour→code map (no inherit).
    """
    if pack is not None:
        _name, day_mask = resolve_pack_name(pack)
    mask = int(day_mask) & 0x7F
    if mask <= 0:
        mask = DAY_MASK_ALL

    code_ids = _clock_code_ids(conn)
    if replace_all_packs:
        conn.execute("DELETE FROM daypart_clocks")
    else:
        conn.execute("DELETE FROM daypart_clocks WHERE day_mask = ?", (mask,))

    for h in range(24):
        code = None
        if hour_clock:
            code = hour_clock.get(str(h), hour_clock.get(h))
        if not code:
            code = DEFAULT_HOUR_CLOCK.get(h, "GENERAL")
        clock_id = code_ids.get(str(code), code_ids.get("GENERAL"))
        if clock_id is None:
            continue
        conn.execute(
            "INSERT INTO daypart_clocks (hour, clock_id, day_mask) VALUES (?, ?, ?)",
            (h, clock_id, mask),
        )
    return load_daypart_grid_from_db(conn, mask, inherit=False)


def clear_daypart_pack(conn, pack_or_mask: Any) -> None:
    """Remove one day_mask pack (weekday/weekend/day); ALL cannot be cleared empty — use Defaults."""
    _name, mask = resolve_pack_name(pack_or_mask)
    if mask == DAY_MASK_ALL:
        raise ValueError("cannot clear ALL pack; use Defaults / save_daypart_grid replace")
    conn.execute("DELETE FROM daypart_clocks WHERE day_mask = ?", (mask,))


def normalize_clock_code(code: str) -> str:
    """Uppercase alphanumeric + underscore clock code (1–32 chars)."""
    raw = str(code or "").strip().upper().replace("-", "_").replace(" ", "_")
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    if not cleaned or not cleaned[0].isalpha():
        raise ValueError("clock code must start with a letter (A–Z)")
    if len(cleaned) > 32:
        raise ValueError("clock code max 32 characters")
    return cleaned


def clone_clock(
    conn,
    source_code: str,
    new_code: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Clone an existing clock (slots + meta) under a new unique code.

    Typical starting points: GENERAL or OVERNIGHT. Returns the new clock dict.
    """
    src = str(source_code or "").strip().upper()
    code = normalize_clock_code(new_code)
    if code in ("GENERAL", "OVERNIGHT") and src != code:
        # Allow cloning *onto* a missing canonical only via ensure; block overwrite
        existing = conn.execute("SELECT id FROM clocks WHERE code=?", (code,)).fetchone()
        if existing:
            raise ValueError(f"cannot overwrite canonical clock {code} via clone")
    row = conn.execute("SELECT * FROM clocks WHERE code = ?", (src,)).fetchone()
    if not row:
        raise KeyError(f"Unknown source clock: {src}")
    taken = conn.execute("SELECT id FROM clocks WHERE code = ?", (code,)).fetchone()
    if taken:
        raise ValueError(f"clock code already exists: {code}")

    src_id = int(row["id"])
    new_name = (str(name).strip() if name else "") or f"{row['name']} (copy)"
    new_desc = (
        str(description).strip()
        if description is not None
        else (row["description"] or f"Cloned from {src}")
    )
    duration = int(row["duration_sec"] or 3600)
    cur = conn.execute(
        """INSERT INTO clocks (code, name, description, duration_sec)
           VALUES (?,?,?,?)""",
        (code, new_name, new_desc, duration),
    )
    new_id = int(cur.lastrowid)
    slots = conn.execute(
        """SELECT position, event_type, category_code, timing_mode, chain_mode,
                  label, offset_sec, duration_sec
           FROM clock_slots WHERE clock_id=? ORDER BY position""",
        (src_id,),
    ).fetchall()
    for s in slots:
        conn.execute(
            """INSERT INTO clock_slots
               (clock_id, position, event_type, category_code, timing_mode,
                chain_mode, label, offset_sec, duration_sec)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_id,
                int(s["position"]),
                s["event_type"],
                s["category_code"],
                s["timing_mode"] or "FLOAT",
                s["chain_mode"] or "AUTO",
                s["label"] or "",
                s["offset_sec"],
                s["duration_sec"],
            ),
        )
    for c in load_clocks_from_db(conn):
        if c["code"] == code:
            return c
    raise RuntimeError("clone_clock: clock missing after insert")


def export_clocks_json(conn, path: Optional[Any] = None) -> Any:
    """Write clocks bundle to data/clocks.json (or path). Returns Path."""
    from pathlib import Path

    from mq_radio.config import DATA_DIR

    target = Path(path) if path is not None else DATA_DIR / "clocks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle = clocks_bundle(conn)
    bundle["exported_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    target.write_text(
        __import__("json").dumps(bundle, indent=2), encoding="utf-8"
    )
    return target


def reset_clock_to_canonical(conn, code: str) -> dict[str, Any]:
    """Restore one clock's slots from CANONICAL_CLOCKS (editor Reset)."""
    clock = get_clock_def(code)
    row = conn.execute("SELECT id FROM clocks WHERE code = ?", (code,)).fetchone()
    if not row:
        ensure_canonical_clocks(conn, reset=True)
        row = conn.execute("SELECT id FROM clocks WHERE code = ?", (code,)).fetchone()
    clock_id = int(row["id"])
    conn.execute(
        """UPDATE clocks SET name=?, description=?, duration_sec=? WHERE id=?""",
        (clock.name, clock.description, clock.duration_sec, clock_id),
    )
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
    for c in load_clocks_from_db(conn):
        if c["code"] == code:
            return c
    raise RuntimeError("reset_clock_to_canonical failed")

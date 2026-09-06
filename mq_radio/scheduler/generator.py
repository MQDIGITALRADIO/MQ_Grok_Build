"""Deterministic Living Log generator — clock expansion + scored selection.

AI never picks MUSIC here. VOICE_TRACK slots are placeholders filled later by
``generate-ai-breaks`` / VT studio → approve.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from mq_radio.db.connection import get_connection
from mq_radio.scheduler.clocks import load_hour_clock_map, normalize_hours
from mq_radio.scheduler.etm_fill import apply_hard_timing_fills, load_filler_pool
from mq_radio.scheduler.rules import HistoryWindow, Ruleset, score_track

ASSET_EVENT_TYPES = {"SWEEPER", "ID", "PROMO", "VOICE_TRACK", "BED", "FILLER"}


@dataclass
class GenerateConstraints:
    """Optional constraints for scored clock expansion (deterministic; no AI song pick)."""

    music_categories: Optional[tuple[str, ...]] = None
    enforce_australian_min: bool = False
    australian_min_pct: Optional[int] = None
    max_same_category_per_hour: Optional[int] = None
    block_explicit: bool = False
    min_score: float = 0.0
    notes_prefix: str = ""

    @classmethod
    def from_mapping(cls, data: Optional[dict]) -> "GenerateConstraints":
        if not data:
            return cls()
        cats = data.get("music_categories")
        if cats is not None:
            cats = tuple(str(c) for c in cats)
        return cls(
            music_categories=cats,
            enforce_australian_min=bool(data.get("enforce_australian_min", False)),
            australian_min_pct=(
                int(data["australian_min_pct"])
                if data.get("australian_min_pct") is not None
                else None
            ),
            max_same_category_per_hour=(
                int(data["max_same_category_per_hour"])
                if data.get("max_same_category_per_hour") is not None
                else None
            ),
            block_explicit=bool(data.get("block_explicit", False)),
            min_score=float(data.get("min_score", 0.0)),
            notes_prefix=str(data.get("notes_prefix") or ""),
        )


def _load_rules(conn, ruleset_code: str = "MQ_DIGITAL") -> tuple[int, Ruleset]:
    row = conn.execute(
        "SELECT * FROM station_rules WHERE code = ? AND active = 1", (ruleset_code,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM station_rules WHERE active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    if not row:
        return 0, Ruleset()
    extra = {}
    if row["rules_json"]:
        extra = json.loads(row["rules_json"])
    return int(row["id"]), Ruleset.from_row(row, extra)


def _tracks_for_category(conn, category_code: Optional[str], event_type: str) -> list[dict]:
    if event_type in ASSET_EVENT_TYPES:
        rows = conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = ?""",
            (event_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    if category_code:
        rows = conn.execute(
            """SELECT t.*, c.code AS category_code FROM tracks t
               LEFT JOIN categories c ON c.id = t.category_id
               WHERE t.active = 1 AND t.event_type = 'MUSIC' AND c.code = ?""",
            (category_code,),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

    rows = conn.execute(
        """SELECT t.*, c.code AS category_code FROM tracks t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.active = 1 AND t.event_type = 'MUSIC'"""
    ).fetchall()
    return [dict(r) for r in rows]


def _pick_best(
    candidates: list[dict],
    when: datetime,
    history: HistoryWindow,
    rules: Ruleset,
    category_code: Optional[str],
    used_ids: set[int],
    *,
    constraints: GenerateConstraints,
    hour_category_counts: dict[str, int],
    hour_music_total: int,
    hour_au_count: int,
) -> tuple[Optional[dict], float]:
    best = None
    best_score = -1.0
    au_min = constraints.australian_min_pct
    if au_min is None:
        au_min = rules.australian_content_min_pct

    def eligible(t: dict) -> tuple[bool, float]:
        if constraints.block_explicit and t.get("explicit"):
            return False, -1e9
        s, _reasons = score_track(t, when, history, rules, category_code)
        if s < 0 or s < constraints.min_score:
            return False, s
        cat = (t.get("category_code") or category_code or "").strip()
        if constraints.music_categories and cat and cat not in constraints.music_categories:
            return False, -1e9
        if constraints.max_same_category_per_hour is not None and cat:
            if hour_category_counts.get(cat, 0) >= constraints.max_same_category_per_hour:
                return False, -1e9
        if constraints.enforce_australian_min and hour_music_total > 0:
            would_au = hour_au_count + (1 if t.get("australian") else 0)
            would_total = hour_music_total + 1
            pct = 100.0 * would_au / would_total
            if would_total >= 4 and pct < au_min and not t.get("australian"):
                return False, -1e9
        return True, s

    def consider(pool, prefer_unused: bool) -> None:
        nonlocal best, best_score
        for t in pool:
            if prefer_unused and t["id"] in used_ids:
                continue
            ok, s = eligible(t)
            if not ok:
                continue
            adj = s + (5.0 if t["id"] not in used_ids else 0.0)
            if adj > best_score:
                best_score = adj
                best = t

    consider(candidates, prefer_unused=True)
    if best is None:
        consider(candidates, prefer_unused=False)
    return best, (best_score if best is not None else -1.0)


def expand_clock_slots(conn, clock_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM clock_slots WHERE clock_id = ? ORDER BY position""",
        (clock_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _parse_scheduled(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def _hour_of(row: dict) -> Optional[int]:
    dt = _parse_scheduled(row.get("scheduled_at"))
    return dt.hour if dt else None


def _snapshot_vt_scripts(conn, event_ids: list[int]) -> dict[int, dict]:
    """Copy vt_scripts rows keyed by log_event_id (FK is NOT NULL — cannot detach)."""
    if not event_ids:
        return {}
    placeholders = ",".join("?" * len(event_ids))
    rows = conn.execute(
        f"SELECT * FROM vt_scripts WHERE log_event_id IN ({placeholders})",
        event_ids,
    ).fetchall()
    return {int(r["log_event_id"]): dict(r) for r in rows}


def _delete_events(conn, event_ids: list[int]) -> None:
    if not event_ids:
        return
    placeholders = ",".join("?" * len(event_ids))
    conn.execute(f"DELETE FROM as_played WHERE log_event_id IN ({placeholders})", event_ids)
    # CASCADE also clears vt_scripts; snapshots must be taken first
    try:
        conn.execute(
            f"DELETE FROM vt_scripts WHERE log_event_id IN ({placeholders})",
            event_ids,
        )
    except Exception:
        pass
    conn.execute(f"DELETE FROM log_events WHERE id IN ({placeholders})", event_ids)


def _restore_vt_script(conn, new_event_id: int, snap: dict) -> int:
    cur = conn.execute(
        """INSERT INTO vt_scripts (
            log_event_id, variation, script_text, daypart, style, station_name,
            status, source, prev_title, prev_artist, next_title, next_artist
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_event_id,
            snap.get("variation") or "silence",
            snap.get("script_text") or "",
            snap.get("daypart"),
            snap.get("style"),
            snap.get("station_name") or "MQ Digital",
            snap.get("status") or "DRAFT",
            snap.get("source") or "AI_TEMPLATE",
            snap.get("prev_title"),
            snap.get("prev_artist"),
            snap.get("next_title"),
            snap.get("next_artist"),
        ),
    )
    # Best-effort restore of audio/trim columns if present (003 migration)
    try:
        conn.execute(
            """UPDATE vt_scripts SET
                audio_path=COALESCE(?, audio_path),
                trim_in_ms=COALESCE(?, trim_in_ms),
                trim_out_ms=COALESCE(?, trim_out_ms),
                recorded_at=COALESCE(?, recorded_at)
               WHERE id=?""",
            (
                snap.get("audio_path"),
                snap.get("trim_in_ms"),
                snap.get("trim_out_ms"),
                snap.get("recorded_at"),
                cur.lastrowid,
            ),
        )
    except Exception:
        try:
            if snap.get("audio_path"):
                conn.execute(
                    "UPDATE vt_scripts SET audio_path=? WHERE id=?",
                    (snap["audio_path"], cur.lastrowid),
                )
        except Exception:
            pass
    return int(cur.lastrowid)


def _build_slot_event(
    *,
    slot: dict,
    when: datetime,
    conn,
    history: HistoryWindow,
    rules: Ruleset,
    used_ids: set[int],
    constraints: GenerateConstraints,
    hour_category_counts: dict[str, int],
    hour_music_total: int,
    hour_au_count: int,
) -> dict:
    et = slot["event_type"]
    cat = slot.get("category_code")
    timing = slot.get("timing_mode") or "FLOAT"
    chain = slot.get("chain_mode") or "AUTO"
    title = slot.get("label") or et
    artist = None
    duration_ms = 0
    track_id = None
    score = None
    notes = slot.get("label")
    australian = False
    if constraints.notes_prefix:
        notes = f"{constraints.notes_prefix}{notes or ''}"

    if et in ("ETM", "BREAK", "COMMAND", "LIVE", "SHOW"):
        duration_ms = 0 if et == "ETM" else (30_000 if et == "BREAK" else 0)
        title = slot.get("label") or et
    elif et == "FILLER":
        # Prefer short FILLER/FL pool carts when the clock places an explicit FILLER slot
        pick_cat = cat or "FL"
        candidates = _tracks_for_category(conn, pick_cat, "FILLER")
        if not candidates:
            candidates = _tracks_for_category(conn, "FL", "FILLER")
        track, score = _pick_best(
            candidates,
            when,
            history,
            rules,
            pick_cat,
            used_ids,
            constraints=constraints,
            hour_category_counts=hour_category_counts,
            hour_music_total=hour_music_total,
            hour_au_count=hour_au_count,
        )
        if track:
            track_id = track["id"]
            title = track["title"]
            artist = track["artist"]
            duration_ms = int(track["duration_ms"] or 0) or 15_000
            used_ids.add(int(track_id))
            cat = track.get("category_code") or pick_cat
        else:
            title = slot.get("label") or "FILLER"
            artist = "MQ Digital"
            duration_ms = 15_000
    elif et == "VOICE_TRACK":
        duration_ms = 8_000
        title = slot.get("label") or "VOICE_TRACK"
        artist = "MQ Digital"
    else:
        pick_cat = cat
        if et == "MUSIC" and constraints.music_categories and cat:
            if cat not in constraints.music_categories:
                pick_cat = constraints.music_categories[0]
        candidates = _tracks_for_category(conn, pick_cat if et == "MUSIC" else cat, et)
        track, score = _pick_best(
            candidates,
            when,
            history,
            rules,
            pick_cat if et == "MUSIC" else cat,
            used_ids,
            constraints=constraints,
            hour_category_counts=hour_category_counts,
            hour_music_total=hour_music_total,
            hour_au_count=hour_au_count,
        )
        if track:
            track_id = track["id"]
            title = track["title"]
            artist = track["artist"]
            duration_ms = int(track["duration_ms"] or 0)
            used_ids.add(int(track_id))
            if et == "MUSIC":
                history.add(track, when)
                australian = bool(track.get("australian"))
                tcat = (track.get("category_code") or pick_cat or "").strip()
                if tcat:
                    hour_category_counts[tcat] = hour_category_counts.get(tcat, 0) + 1
        else:
            title = f"[UNFILLED {et}/{cat or '-'}]"
            duration_ms = 5000

    return {
        "scheduled_at": when.strftime("%Y-%m-%dT%H:%M:%S"),
        "event_type": et,
        "track_id": track_id,
        "title": title,
        "artist": artist,
        "duration_ms": duration_ms,
        "timing_mode": timing,
        "chain_mode": chain,
        "status": "COMMITTED",
        "manual_flag": "AUTO",
        "category_code": cat,
        "clock_slot_id": slot.get("id"),
        "score": score,
        "notes": notes,
        "_when": when,
        "_is_music": et == "MUSIC" and track_id is not None,
        "_australian": australian,
    }


def _merge_manuals_into_hour(auto_events: list[dict], manuals: list[dict]) -> list[dict]:
    """Merge MANUAL rows into an hour by scheduled_at (survives clock length changes)."""
    if not manuals:
        return auto_events

    used_auto: set[int] = set()
    merged: list[dict] = []
    for m in sorted(manuals, key=lambda r: r.get("scheduled_at") or ""):
        m_when = _parse_scheduled(m.get("scheduled_at"))
        best_i = None
        best_dist: Optional[float] = None
        for i, ev in enumerate(auto_events):
            if i in used_auto:
                continue
            aw = ev.get("_when") or _parse_scheduled(ev.get("scheduled_at"))
            if m_when and aw:
                dist = abs((aw - m_when).total_seconds())
            else:
                dist = 99999.0
            if m.get("event_type") and ev.get("event_type") != m.get("event_type"):
                dist += 120.0
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i = i
        row = {
            "scheduled_at": m.get("scheduled_at"),
            "event_type": m.get("event_type"),
            "track_id": m.get("track_id"),
            "title": m.get("title"),
            "artist": m.get("artist"),
            "duration_ms": m.get("duration_ms") or 0,
            "timing_mode": m.get("timing_mode") or "FLOAT",
            "chain_mode": m.get("chain_mode") or "AUTO",
            "status": m.get("status") or "COMMITTED",
            "manual_flag": "MANUAL",
            "category_code": m.get("category_code"),
            "clock_slot_id": m.get("clock_slot_id"),
            "score": m.get("score"),
            "notes": m.get("notes"),
            "_when": m_when,
            "_preserve_id": m.get("id"),
            "_vt_script_id": m.get("_vt_script_id"),
        }
        if best_i is not None and best_dist is not None and best_dist <= 180.0:
            used_auto.add(best_i)
            if not row["scheduled_at"] and auto_events[best_i].get("scheduled_at"):
                row["scheduled_at"] = auto_events[best_i]["scheduled_at"]
                row["_when"] = auto_events[best_i].get("_when")
        merged.append(row)

    for i, ev in enumerate(auto_events):
        if i not in used_auto:
            merged.append(ev)

    merged.sort(
        key=lambda e: (
            e.get("scheduled_at") or "",
            0 if e.get("manual_flag") == "MANUAL" else 1,
        )
    )
    return merged


def _seed_history(conn) -> HistoryWindow:
    history = HistoryWindow()
    for row in conn.execute(
        """SELECT a.artist, a.title, a.played_at, a.track_id, t.album
           FROM as_played a
           LEFT JOIN tracks t ON t.id = a.track_id
           ORDER BY a.played_at DESC LIMIT 200"""
    ).fetchall():
        dt = datetime.fromisoformat(row["played_at"]) if row["played_at"] else None
        if dt:
            history.plays.append(
                {
                    "track_id": row["track_id"],
                    "artist": (row["artist"] or "").lower(),
                    "title": (row["title"] or "").lower(),
                    "album": (row["album"] or "").lower() if row["album"] else "",
                    "played_at": dt,
                }
            )
    history.plays.sort(key=lambda p: p["played_at"])
    return history


def generate_log(
    log_date: str,
    db_path: Optional[Path] = None,
    force: bool = False,
    ruleset_code: str = "MQ_DIGITAL",
    hours: Optional[Iterable[int]] = None,
    constraints: Optional[GenerateConstraints | dict] = None,
) -> dict:
    """
    Generate a Living Log for log_date (YYYY-MM-DD).

    - ``hours``: optional subset (e.g. overnight ``[23,0,1,2,3,4]``). None = 24h.
    - ``force``: overwrite MANUAL rows too (within selected hours).
    - ``constraints``: category / AU / score limits — never AI song pick.
    """
    if isinstance(constraints, dict):
        constraints = GenerateConstraints.from_mapping(constraints)
    constraints = constraints or GenerateConstraints()
    selected = normalize_hours(hours)

    conn = get_connection(db_path)
    rules_id, rules = _load_rules(conn, ruleset_code)

    existing = conn.execute(
        "SELECT * FROM daily_logs WHERE log_date = ?", (log_date,)
    ).fetchone()
    if existing:
        daily_log_id = int(existing["id"])
        conn.execute(
            """UPDATE daily_logs SET status='DRAFT', ruleset_id=?, generated_at=datetime('now')
               WHERE id=?""",
            (rules_id, daily_log_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO daily_logs (log_date, status, ruleset_id, generated_at)
               VALUES (?, 'DRAFT', ?, datetime('now'))""",
            (log_date, rules_id),
        )
        daily_log_id = int(cur.lastrowid)

    current = [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM log_events WHERE daily_log_id = ? ORDER BY position""",
            (daily_log_id,),
        ).fetchall()
    ]

    manuals_by_hour: dict[int, list[dict]] = {h: [] for h in range(24)}
    vt_snapshots: dict[int, dict] = {}  # old log_event_id → vt_scripts row

    hours_to_build = selected if selected is not None else list(range(24))
    hours_set = set(hours_to_build)

    # Partition: keep vs rebuild
    keep_events: list[dict] = []
    rebuild_ids: list[int] = []
    for row in current:
        h = _hour_of(row)
        if selected is not None and h is not None and h not in hours_set:
            keep_events.append(row)
            continue
        rebuild_ids.append(int(row["id"]))
        if not force and row.get("manual_flag") == "MANUAL" and h is not None:
            manuals_by_hour[h].append(row)

    # Snapshot VT scripts before CASCADE delete (FK is NOT NULL)
    vt_snapshots.update(_snapshot_vt_scripts(conn, rebuild_ids))
    for hh in manuals_by_hour.values():
        for m in hh:
            eid = m.get("id")
            if eid is not None and int(eid) in vt_snapshots:
                m["_vt_snap"] = vt_snapshots[int(eid)]

    _delete_events(conn, rebuild_ids)

    hour_clocks = load_hour_clock_map(conn, log_date)
    default_clock = hour_clocks.get(0) or next(iter(hour_clocks.values()), 1)
    history = _seed_history(conn)
    used_ids: set[int] = set()

    for row in keep_events:
        if row.get("event_type") == "MUSIC" and row.get("track_id"):
            when = _parse_scheduled(row.get("scheduled_at"))
            if when:
                history.add(
                    {
                        "id": row["track_id"],
                        "artist": row.get("artist") or "",
                        "title": row.get("title") or "",
                        "album": "",
                    },
                    when,
                )
        if row.get("track_id"):
            used_ids.add(int(row["track_id"]))

    base = datetime.strptime(log_date, "%Y-%m-%d")
    built: list[dict] = []
    generated = 0
    preserved = 0
    filler_pool = load_filler_pool(conn)
    fill_totals = {
        "windows": 0,
        "stretched_ms": 0,
        "compressed_ms": 0,
        "filler_inserted": 0,
        "filler_grown_ms": 0,
        "overage_ms": 0,
        "under_after_ms": 0,
    }

    for hour in hours_to_build:
        clock_id = hour_clocks.get(hour, default_clock)
        slots = expand_clock_slots(conn, clock_id)
        slot_count = max(len(slots), 1)
        hour_start = base + timedelta(hours=hour)
        step_sec = 3600.0 / slot_count
        hour_category_counts: dict[str, int] = {}
        hour_music_total = 0
        hour_au_count = 0
        auto_events: list[dict] = []

        for slot_index, slot in enumerate(slots):
            if slot.get("offset_sec") is not None:
                when = hour_start + timedelta(seconds=int(slot["offset_sec"]))
            else:
                when = hour_start + timedelta(seconds=step_sec * slot_index)
            ev = _build_slot_event(
                slot=slot,
                when=when,
                conn=conn,
                history=history,
                rules=rules,
                used_ids=used_ids,
                constraints=constraints,
                hour_category_counts=hour_category_counts,
                hour_music_total=hour_music_total,
                hour_au_count=hour_au_count,
            )
            if ev.get("_is_music"):
                hour_music_total += 1
                if ev.get("_australian"):
                    hour_au_count += 1
            auto_events.append(ev)

        if force:
            hour_events = auto_events
        else:
            hour_events = _merge_manuals_into_hour(auto_events, manuals_by_hour[hour])
            preserved += sum(1 for e in hour_events if e.get("manual_flag") == "MANUAL")
        # Hard ETM / HIT / HARD fills: stretch FLOAT or insert FILLER toward markers
        hour_events, fill_stats = apply_hard_timing_fills(
            hour_events, hour_start=hour_start, filler_pool=filler_pool
        )
        fs = fill_stats.as_dict()
        for k in fill_totals:
            fill_totals[k] += int(fs.get(k) or 0)
        generated += sum(1 for e in hour_events if e.get("manual_flag") != "MANUAL")
        built.extend(hour_events)

    # Rewrite positions: shift keep rows, then emit full ordered list
    if keep_events:
        conn.execute(
            "UPDATE log_events SET position = position + 100000 WHERE daily_log_id = ?",
            (daily_log_id,),
        )

    final_rows: list[dict] = [{**r, "_keep": True} for r in keep_events] + built
    final_rows.sort(
        key=lambda e: (
            e.get("scheduled_at") or "",
            0 if e.get("manual_flag") == "MANUAL" else 1,
            int(e.get("position") or 0),
        )
    )

    # Remove keep rows from DB (restore their VT snapshots after insert)
    keep_ids = [int(r["id"]) for r in keep_events if r.get("id") is not None]
    keep_snaps = _snapshot_vt_scripts(conn, keep_ids)
    vt_snapshots.update(keep_snaps)
    for r in keep_events:
        eid = r.get("id")
        if eid is not None and int(eid) in keep_snaps:
            r["_vt_snap"] = keep_snaps[int(eid)]
    _delete_events(conn, keep_ids)

    position = 0
    for ev in final_rows:
        old_id = ev.get("id") if ev.get("_keep") else ev.get("_preserve_id")
        scheduled_at = ev.get("scheduled_at")
        if not scheduled_at and ev.get("_when"):
            scheduled_at = ev["_when"].strftime("%Y-%m-%dT%H:%M:%S")
        cur = conn.execute(
            """INSERT INTO log_events (
                daily_log_id, position, scheduled_at, event_type, track_id,
                title, artist, duration_ms, timing_mode, chain_mode,
                status, manual_flag, category_code, clock_slot_id, score, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                daily_log_id,
                position,
                scheduled_at,
                ev.get("event_type"),
                ev.get("track_id"),
                ev.get("title"),
                ev.get("artist"),
                int(ev.get("duration_ms") or 0),
                ev.get("timing_mode") or "FLOAT",
                ev.get("chain_mode") or "AUTO",
                ev.get("status") or "COMMITTED",
                ev.get("manual_flag") or "AUTO",
                ev.get("category_code"),
                ev.get("clock_slot_id"),
                ev.get("score"),
                ev.get("notes"),
            ),
        )
        new_id = int(cur.lastrowid)
        snap = ev.get("_vt_snap")
        if not snap and old_id is not None:
            snap = vt_snapshots.get(int(old_id))
        if snap:
            _restore_vt_script(conn, new_id, snap)
        position += 1

    conn.execute(
        "UPDATE daily_logs SET status='COMMITTED', generated_at=datetime('now') WHERE id=?",
        (daily_log_id,),
    )
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM log_events WHERE daily_log_id=?", (daily_log_id,)
    ).fetchone()["c"]
    vt_count = conn.execute(
        """SELECT COUNT(*) AS c FROM log_events
           WHERE daily_log_id=? AND event_type='VOICE_TRACK'""",
        (daily_log_id,),
    ).fetchone()["c"]
    # Hour coverage — operator/CI hardening for deterministic 24h generate
    hour_rows = conn.execute(
        """SELECT CAST(substr(scheduled_at, 12, 2) AS INTEGER) AS h, COUNT(*) AS c
           FROM log_events WHERE daily_log_id=?
           GROUP BY h ORDER BY h""",
        (daily_log_id,),
    ).fetchall()
    events_per_hour = {int(r["h"]): int(r["c"]) for r in hour_rows if r["h"] is not None}
    hours_present = sorted(events_per_hour.keys())
    expected_hours = list(range(24)) if selected is None else list(hours_to_build)
    missing_hours = [h for h in expected_hours if h not in events_per_hour]
    empty_hours = [h for h in expected_hours if events_per_hour.get(h, 0) <= 0]
    conn.close()

    return {
        "daily_log_id": daily_log_id,
        "events": total,
        "log_date": log_date,
        "generated": generated,
        "preserved_manual": preserved,
        "force": force,
        "ruleset_id": rules_id,
        "hours": hours_to_build,
        "voice_tracks": vt_count,
        "hours_covered": hours_present,
        "missing_hours": missing_hours,
        "empty_hours": empty_hours,
        "events_per_hour": {str(k): v for k, v in sorted(events_per_hour.items())},
        "coverage_complete": len(missing_hours) == 0 and len(empty_hours) == 0,
        "constraints": {
            "music_categories": list(constraints.music_categories)
            if constraints.music_categories
            else None,
            "enforce_australian_min": constraints.enforce_australian_min,
            "max_same_category_per_hour": constraints.max_same_category_per_hour,
            "block_explicit": constraints.block_explicit,
            "min_score": constraints.min_score,
        },
        "etm_fill": fill_totals,
    }


def generate_hour(
    log_date: str,
    hour: int,
    db_path: Optional[Path] = None,
    force: bool = False,
    ruleset_code: str = "MQ_DIGITAL",
    constraints: Optional[GenerateConstraints | dict] = None,
) -> dict:
    """Generate / refresh a single wall-clock hour of the Living Log."""
    return generate_log(
        log_date,
        db_path=db_path,
        force=force,
        ruleset_code=ruleset_code,
        hours=[int(hour) % 24],
        constraints=constraints,
    )

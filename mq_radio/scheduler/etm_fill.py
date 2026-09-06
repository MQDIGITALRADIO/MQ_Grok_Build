"""Hard ETM / HIT / HARD timing fills for Living Log + MockEngine.

Broadcast behaviour (documented for operators / tests)
======================================================

Hard markers
------------
Events that pin wall-clock airtime:

* ``event_type == "ETM"`` — Exact Time Marker (zero-duration hit from the hour clock)
* ``timing_mode in {"HIT", "HARD"}`` — top-of-hour IDs, stopsets, hard breaks, …

``scheduled_at`` on these rows is the **target** airtime (naive local studio clock).

Fill / stretch (scheduler post-pass)
------------------------------------
Between consecutive hard markers (and from hour start → first marker):

1. Sum planned ``duration_ms`` of FLOAT (and other non-hard) content in the window.
2. Compare to the wall window length (marker_at − window_start).
3. **Under** (content short of the hit):
   - Prefer stretching the last stretchable MUSIC (up to ``MAX_STRETCH_MS``).
   - If still short, insert a ``FILLER`` from the short-cart pool
     (FILLER / ID / SWEEPER / BED under ``data/filler/`` + seed fixtures),
     preferring real carts over a duration-only stub; grow an existing FILLER
     when present so the cumulative duration lands on the marker.
4. **Over** (content past the hit):
   - Compress FLOAT MUSIC slightly (floor ``MIN_MUSIC_MS``), never past the floor.
   - Remaining overage is recorded in ``notes`` / return stats (late into the hit);
     we do **not** delete operator MANUAL rows.
5. Re-stamp ``scheduled_at`` for FLOAT rows from cumulative durations so the log
   leads cleanly into the hard marker. Hard marker ``scheduled_at`` stays fixed.

Engine (MockEngine)
-------------------
When starting a cart, if a future hard marker exists and the remaining planned
content (this cart + FLOAT successors before the marker) does not match the
slack to the marker:

* Early → stretch this cart's air duration (MUSIC / FILLER) toward the hit.
* Late  → trim air duration toward a safe floor so AUTO can recover.

TO TIME / ETM readout on the desk already surfaces the next marker; this module
deepens scheduler + engine so regenerate and playout honour those hits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

# Stretch / compress bounds (broadcast-sane defaults)
MAX_STRETCH_MS = 90_000  # +1:30 max on one music cart
MAX_COMPRESS_FRAC = 0.12  # shave at most 12% of a FLOAT music
MIN_MUSIC_MS = 90_000  # never compress music below ~1:30 air
MIN_OTHER_MS = 3_000
MAX_FILLER_INSERT_MS = 180_000  # 3:00 filler cap per window
DEFAULT_FILLER_MS = 30_000

HARD_TIMING = frozenset({"HIT", "HARD"})

# Preferred event types when selecting a real cart for ETM FILLER inserts
FILLER_POOL_TYPES = ("FILLER", "ID", "SWEEPER", "BED")
FILLER_POOL_CODES = frozenset({"FL", "FILLER", "ID", "SW", "BED"})


def load_filler_pool(conn) -> list[dict]:
    """Load short FILLER/ID/SWEEPER/BED carts for ETM under-fills.

    Operators seed these via ``seed-demo`` / ``ensure_filler_pool`` under
    ``data/filler/`` (gitignored) plus fixture imaging carts.
    """
    rows = conn.execute(
        """SELECT t.id, t.title, t.artist, t.duration_ms, t.event_type,
                  COALESCE(c.code, t.rotation_category, '') AS category_code
           FROM tracks t
           LEFT JOIN categories c ON c.id = t.category_id
           WHERE t.active = 1
             AND (
               UPPER(t.event_type) IN ('FILLER','ID','SWEEPER','BED')
               OR UPPER(COALESCE(c.code,'')) IN ('FL','FILLER','ID','SW','BED')
               OR UPPER(COALESCE(t.rotation_category,'')) IN ('FILLER','ID','SWEEPER','BED')
             )
           ORDER BY
             CASE UPPER(t.event_type)
               WHEN 'FILLER' THEN 0
               WHEN 'ID' THEN 1
               WHEN 'SWEEPER' THEN 2
               ELSE 3
             END,
             t.duration_ms ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


def pick_filler_cart(
    pool: list[dict],
    need_ms: int,
    *,
    used_ids: Optional[set[int]] = None,
) -> Optional[dict]:
    """Choose the best short cart for an under-fill of ``need_ms``.

    Prefers FILLER event_type, then ID/SWEEPER/BED. Favours duration closest to
    need (slightly under preferred so we can stretch the event airtime).
    """
    if need_ms <= 0 or not pool:
        return None
    used = used_ids or set()
    candidates = []
    for t in pool:
        tid = t.get("id")
        if tid is not None and int(tid) in used:
            continue
        dur = max(0, int(t.get("duration_ms") or 0))
        if dur < 500:
            continue
        et = str(t.get("event_type") or "").upper()
        type_rank = {"FILLER": 0, "ID": 1, "SWEEPER": 2, "BED": 3}.get(et, 4)
        # Prefer under/equal need; overage penalised
        over = max(0, dur - need_ms)
        under = max(0, need_ms - dur)
        score = (type_rank, over, under, dur)
        candidates.append((score, t))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return dict(candidates[0][1])



def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    text = text.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_hard_marker(ev: dict) -> bool:
    et = str(ev.get("event_type") or "").upper()
    if et == "ETM":
        return True
    timing = str(ev.get("timing_mode") or "").upper()
    return timing in HARD_TIMING


def is_stretchable(ev: dict) -> bool:
    if is_hard_marker(ev):
        return False
    if str(ev.get("manual_flag") or "").upper() == "MANUAL":
        return False
    et = str(ev.get("event_type") or "").upper()
    return et in ("MUSIC", "FILLER", "BED")


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class FillStats:
    windows: int = 0
    stretched_ms: int = 0
    compressed_ms: int = 0
    filler_inserted: int = 0
    filler_grown_ms: int = 0
    overage_ms: int = 0
    under_after_ms: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "windows": self.windows,
            "stretched_ms": self.stretched_ms,
            "compressed_ms": self.compressed_ms,
            "filler_inserted": self.filler_inserted,
            "filler_grown_ms": self.filler_grown_ms,
            "overage_ms": self.overage_ms,
            "under_after_ms": self.under_after_ms,
            "notes": list(self.notes),
        }


def _window_content_ms(events: list[dict]) -> int:
    total = 0
    for e in events:
        if is_hard_marker(e):
            continue
        total += max(0, int(e.get("duration_ms") or 0))
    return total


def _stretch_last(events: list[dict], need_ms: int, stats: FillStats) -> int:
    """Add up to need_ms onto the last stretchable event. Returns applied ms."""
    if need_ms <= 0:
        return 0
    for e in reversed(events):
        if not is_stretchable(e):
            continue
        et = str(e.get("event_type") or "").upper()
        cap = MAX_STRETCH_MS if et == "MUSIC" else MAX_FILLER_INSERT_MS
        add = min(need_ms, cap)
        if add <= 0:
            continue
        e["duration_ms"] = int(e.get("duration_ms") or 0) + add
        note = e.get("notes") or ""
        tag = f"[ETM stretch +{add}ms]"
        if tag not in str(note):
            e["notes"] = f"{note} {tag}".strip() if note else tag
        stats.stretched_ms += add
        return add
    return 0


def _compress_float(events: list[dict], over_ms: int, stats: FillStats) -> int:
    """Shave over_ms from FLOAT stretchables (music first). Returns removed ms."""
    if over_ms <= 0:
        return 0
    removed = 0
    for e in reversed(events):
        if over_ms - removed <= 0:
            break
        if not is_stretchable(e):
            continue
        if str(e.get("timing_mode") or "FLOAT").upper() not in ("FLOAT", "SOFT"):
            continue
        et = str(e.get("event_type") or "").upper()
        dur = int(e.get("duration_ms") or 0)
        floor = MIN_MUSIC_MS if et == "MUSIC" else MIN_OTHER_MS
        max_shave = min(int(dur * MAX_COMPRESS_FRAC), max(0, dur - floor), over_ms - removed)
        if max_shave <= 0:
            continue
        e["duration_ms"] = dur - max_shave
        note = e.get("notes") or ""
        tag = f"[ETM compress -{max_shave}ms]"
        if tag not in str(note):
            e["notes"] = f"{note} {tag}".strip() if note else tag
        removed += max_shave
        stats.compressed_ms += max_shave
    return removed


def _insert_or_grow_filler(
    events: list[dict],
    need_ms: int,
    *,
    when: datetime,
    stats: FillStats,
    filler_pool: Optional[list[dict]] = None,
    used_track_ids: Optional[set[int]] = None,
) -> int:
    """Grow trailing FILLER or insert from the short-cart pool / stub.

    Prefer real FILLER/ID/SWEEPER/BED carts when ``filler_pool`` is provided.
    Returns applied ms toward the hard marker.
    """
    if need_ms <= 0:
        return 0
    apply = min(need_ms, MAX_FILLER_INSERT_MS)
    used = used_track_ids if used_track_ids is not None else set()

    for e in reversed(events):
        if str(e.get("event_type") or "").upper() == "FILLER":
            cur = int(e.get("duration_ms") or 0)
            # Cap single-window growth; existing stretched carts may already be long
            add = min(apply, MAX_FILLER_INSERT_MS)
            if add <= 0:
                break
            e["duration_ms"] = cur + add
            stats.filler_grown_ms += add
            note = e.get("notes") or ""
            tag = f"[ETM filler +{add}ms]"
            if tag not in str(note):
                e["notes"] = f"{note} {tag}".strip() if note else tag
            return add

    cart = pick_filler_cart(filler_pool or [], apply, used_ids=used)
    title = "ETM FILL"
    artist = "MQ Digital"
    track_id = None
    category_code = "FL"
    cart_dur = None
    notes = f"[ETM fill {apply}ms toward hard marker]"
    if cart:
        track_id = int(cart["id"]) if cart.get("id") is not None else None
        title = cart.get("title") or title
        artist = cart.get("artist") or artist
        category_code = (cart.get("category_code") or "FL") or "FL"
        cart_dur = max(0, int(cart.get("duration_ms") or 0))
        et = str(cart.get("event_type") or "FILLER").upper()
        notes = f"[ETM fill cart {et} #{track_id} · need {apply}ms]"
        if track_id is not None:
            used.add(track_id)

    # Air duration = need (capped). Cart file may be shorter (engine stretch) or
    # longer (trim toward need in engine); scheduler stamps the window need.
    duration_ms = apply if apply >= 1000 else max(apply, min(DEFAULT_FILLER_MS, need_ms))
    if apply < DEFAULT_FILLER_MS:
        duration_ms = apply
    # If we have a cart longer than need, still stamp need so we hit the marker
    # (engine may trim). If cart is shorter, stamp need (stretch air toward hit).
    if cart_dur and cart_dur > 0 and apply >= cart_dur:
        # Prefer playing the cart once at cart length when that closes most of the gap
        # and remaining under will be noted; but for hard hits use exact apply.
        duration_ms = apply

    filler = {
        "scheduled_at": _fmt(when),
        "event_type": "FILLER",
        "track_id": track_id,
        "title": title,
        "artist": artist,
        "duration_ms": duration_ms,
        "timing_mode": "FLOAT",
        "chain_mode": "AUTO",
        "status": "COMMITTED",
        "manual_flag": "AUTO",
        "category_code": category_code,
        "clock_slot_id": None,
        "score": None,
        "notes": notes,
        "_when": when,
        "_etm_fill": True,
        "_filler_cart_ms": cart_dur,
    }
    events.append(filler)
    stats.filler_inserted += 1
    if track_id is not None:
        stats.notes.append(f"filler cart #{track_id} ({title}) for {apply}ms")
    return int(filler["duration_ms"])


def _restamp_window(events: list[dict], start: datetime) -> None:
    cursor = start
    for e in events:
        if is_hard_marker(e):
            # Keep hard scheduled_at; advance cursor to marker (or past if late)
            when = _parse_dt(e.get("scheduled_at")) or e.get("_when") or cursor
            e["scheduled_at"] = _fmt(when) if isinstance(when, datetime) else e.get("scheduled_at")
            e["_when"] = when if isinstance(when, datetime) else cursor
            cursor = e["_when"]
            continue
        e["_when"] = cursor
        e["scheduled_at"] = _fmt(cursor)
        cursor = cursor + timedelta(milliseconds=max(0, int(e.get("duration_ms") or 0)))


def apply_hard_timing_fills(
    events: list[dict],
    *,
    hour_start: Optional[datetime] = None,
    filler_pool: Optional[list[dict]] = None,
) -> tuple[list[dict], FillStats]:
    """Post-process an hour (or day) event list toward HIT/HARD/ETM markers.

    Returns a **new** list (may include inserted FILLER rows) and fill stats.
    Hard marker scheduled_at values are preserved; FLOAT rows are re-stamped.

    When ``filler_pool`` is supplied (from ``load_filler_pool``), under-fills
    prefer real short carts over a duration-only stub.
    """
    stats = FillStats()
    if not events:
        return [], stats

    work = [dict(e) for e in events]
    used_track_ids: set[int] = set()
    for e in work:
        tid = e.get("track_id")
        if tid is not None:
            try:
                used_track_ids.add(int(tid))
            except (TypeError, ValueError):
                pass
    # Determine hour_start from first event if needed
    first_when = None
    for e in work:
        first_when = e.get("_when") or _parse_dt(e.get("scheduled_at"))
        if first_when:
            break
    if hour_start is None:
        hour_start = first_when.replace(minute=0, second=0, microsecond=0) if first_when else None
    if hour_start is None:
        return work, stats

    # Split into segments ending at each hard marker
    segments: list[tuple[list[dict], Optional[dict]]] = []
    buf: list[dict] = []
    for e in work:
        if is_hard_marker(e):
            segments.append((buf, e))
            buf = []
        else:
            buf.append(e)
    trailing = buf

    out: list[dict] = []
    window_start = hour_start

    for content, marker in segments:
        stats.windows += 1
        marker_at = marker.get("_when") or _parse_dt(marker.get("scheduled_at"))
        if marker_at is None:
            # Keep as-is
            _restamp_window(content, window_start)
            out.extend(content)
            out.append(marker)
            window_start = window_start  # unchanged
            continue

        target_ms = int((marker_at - window_start).total_seconds() * 1000)
        if target_ms < 0:
            target_ms = 0
        content_ms = _window_content_ms(content)
        delta = target_ms - content_ms

        if delta > 500:  # under by >0.5s
            applied = _stretch_last(content, delta, stats)
            still = delta - applied
            if still > 500:
                grown = _insert_or_grow_filler(
                    content,
                    still,
                    when=window_start + timedelta(milliseconds=content_ms + applied),
                    stats=stats,
                    filler_pool=filler_pool,
                    used_track_ids=used_track_ids,
                )
                still -= grown
            if still > 1000:
                stats.under_after_ms += still
                stats.notes.append(
                    f"under {still}ms before {marker.get('event_type')}@{marker.get('scheduled_at')}"
                )
        elif delta < -500:  # over
            removed = _compress_float(content, -delta, stats)
            still_over = (-delta) - removed
            if still_over > 1000:
                stats.overage_ms += still_over
                stats.notes.append(
                    f"over {still_over}ms into {marker.get('event_type')}@{marker.get('scheduled_at')}"
                )
                note = marker.get("notes") or ""
                tag = f"[ETM late +{still_over}ms]"
                if tag not in str(note):
                    marker["notes"] = f"{note} {tag}".strip() if note else tag

        _restamp_window(content, window_start)
        out.extend(content)
        # Pin marker
        marker = dict(marker)
        marker["_when"] = marker_at
        marker["scheduled_at"] = _fmt(marker_at)
        if str(marker.get("event_type") or "").upper() == "ETM":
            marker["duration_ms"] = 0
        out.append(marker)
        window_start = marker_at

    if trailing:
        _restamp_window(trailing, window_start)
        out.extend(trailing)

    return out, stats


def next_hard_after(
    events: Iterable[dict],
    *,
    after_position: Optional[int] = None,
    after_scheduled: Optional[datetime] = None,
) -> Optional[dict]:
    """Return the next hard marker after a position or scheduled time."""
    best: Optional[tuple[datetime, dict]] = None
    for e in events:
        if not is_hard_marker(e):
            continue
        if after_position is not None and e.get("position") is not None:
            if int(e["position"]) <= int(after_position):
                continue
        when = _parse_dt(e.get("scheduled_at"))
        if when is None:
            continue
        if after_scheduled is not None and when <= after_scheduled:
            continue
        if best is None or when < best[0]:
            best = (when, e)
    return best[1] if best else None


def engine_air_duration_toward_hit(
    *,
    base_duration_ms: int,
    event: dict,
    following: list[dict],
    now: Optional[datetime] = None,
    max_stretch_ms: int = MAX_STRETCH_MS,
) -> tuple[int, dict]:
    """Adjust playout duration so AUTO fills/stretches toward the next hard marker.

    ``following`` = remaining committed events after ``event`` (same log), including
    the hard marker. Returns (air_duration_ms, meta).
    """
    now = now or datetime.now()
    base = max(0, int(base_duration_ms or 0))
    meta: dict[str, Any] = {
        "base_ms": base,
        "adjusted_ms": base,
        "action": "none",
        "marker": None,
        "slack_ms": None,
    }
    if not is_stretchable(event) and str(event.get("event_type") or "").upper() not in (
        "MUSIC",
        "FILLER",
        "BED",
        "VOICE_TRACK",
        "SWEEPER",
        "ID",
        "PROMO",
    ):
        return base, meta

    marker = None
    for e in following:
        if is_hard_marker(e):
            marker = e
            break
    if not marker:
        return base, meta

    marker_at = _parse_dt(marker.get("scheduled_at"))
    if marker_at is None:
        return base, meta

    # Planned content after this cart until (not including) the marker
    after_ms = 0
    for e in following:
        if e is marker or (e.get("id") is not None and marker.get("id") is not None and e.get("id") == marker.get("id")):
            break
        if is_hard_marker(e):
            break
        after_ms += max(0, int(e.get("duration_ms") or 0))

    slack_ms = int((marker_at - now).total_seconds() * 1000) - after_ms
    meta["slack_ms"] = slack_ms
    meta["marker"] = {
        "id": marker.get("id"),
        "event_type": marker.get("event_type"),
        "timing_mode": marker.get("timing_mode"),
        "scheduled_at": marker.get("scheduled_at"),
        "title": marker.get("title"),
    }

    et = str(event.get("event_type") or "").upper()
    floor = MIN_MUSIC_MS if et == "MUSIC" else MIN_OTHER_MS

    if slack_ms > base + 500:
        # Early — stretch toward hit
        stretch = min(slack_ms - base, max_stretch_ms)
        if stretch > 250 and et in ("MUSIC", "FILLER", "BED", "VOICE_TRACK"):
            adj = base + stretch
            meta["adjusted_ms"] = adj
            meta["action"] = "stretch"
            return adj, meta
    elif slack_ms < base - 500:
        # Late — trim toward floor so we recover into the hit
        target = max(floor, slack_ms)
        if target < base - 250:
            meta["adjusted_ms"] = target
            meta["action"] = "trim"
            return target, meta

    return base, meta

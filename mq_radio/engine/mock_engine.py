"""MockEngine — Living Log playout with real ON-AIR hold for timers.

AUTO honors end-pulse (ingest outro_ms): advances the next Living Log event when
the cart enters its end-pulse window — not only at absolute EOF.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.engine.base import EngineState, PlayoutEngine
from mq_radio.engine.session import SESSION
from mq_radio.production.ramps import profile_for_context


def _resolve_end_pulse(outro_ms: int, duration_ms: int) -> int:
    """Clamp outro/end-pulse so AUTO can fire before EOF without negative windows."""
    dur = max(0, int(duration_ms or 0))
    pulse = max(0, int(outro_ms or 0))
    if dur <= 0:
        return 0
    if pulse <= 0:
        # Default half-second end flash so AUTO still has a pulse edge at EOF
        return min(500, max(1, dur // 20))
    if pulse >= dur:
        return min(2000, max(250, dur // 10))
    # Keep at least ~55% of cart before pulse so we don't chain instantly
    max_pulse = max(250, int(dur * 0.45))
    return min(pulse, max_pulse)


def _air_duration(ev) -> int:
    duration = int(ev["duration_ms"] or 0)
    if (ev["event_type"] or "") == "MUSIC" and duration < 90_000:
        return max(duration, 180_000)  # 3:00 floor for music
    if duration < 5_000:
        return max(duration, 8_000)
    return duration


class MockEngine(PlayoutEngine):
    def __init__(self, log_date: str, db_path: Optional[Path] = None):
        self.log_date = log_date
        self.db_path = db_path
        self._state = EngineState(message="mock idle")

    def _daily_log_id(self, conn) -> Optional[int]:
        row = conn.execute(
            "SELECT id FROM daily_logs WHERE log_date = ?", (self.log_date,)
        ).fetchone()
        return int(row["id"]) if row else None

    def _next_event(self, conn, daily_log_id: int):
        return conn.execute(
            """SELECT e.*,
                      COALESCE(t.intro_ms, 0) AS intro_ms,
                      COALESCE(t.outro_ms, 0) AS outro_ms,
                      COALESCE(t.file_path, '') AS file_path
               FROM log_events e
               LEFT JOIN tracks t ON t.id = e.track_id
               WHERE e.daily_log_id = ? AND e.status IN ('COMMITTED', 'DRAFT')
                 AND e.event_type != 'ETM'
               ORDER BY e.position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()

    def _on_air_event(self, conn, daily_log_id: int):
        return conn.execute(
            """SELECT e.*,
                      COALESCE(t.intro_ms, 0) AS intro_ms,
                      COALESCE(t.outro_ms, 0) AS outro_ms,
                      COALESCE(t.file_path, '') AS file_path
               FROM log_events e
               LEFT JOIN tracks t ON t.id = e.track_id
               WHERE e.daily_log_id = ? AND e.status = 'ON_AIR'
               ORDER BY e.position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()

    def _bind_session(self, ev, duration: int) -> None:
        keys = ev.keys() if hasattr(ev, "keys") else ev
        intro = int(ev["intro_ms"] or 0) if "intro_ms" in keys else 0
        outro = int(ev["outro_ms"] or 0) if "outro_ms" in keys else 0
        file_path = ""
        if "file_path" in keys and ev["file_path"]:
            file_path = str(ev["file_path"])
        track_id = int(ev["track_id"]) if ev["track_id"] is not None else None
        etype = ev["event_type"] or ""
        pulse = _resolve_end_pulse(outro, duration)
        daypart = ""
        sched = ev["scheduled_at"] if "scheduled_at" in keys else None
        if sched:
            try:
                hour = int(str(sched).split("T")[1].split(":")[0])
                if hour < 5 or hour >= 23:
                    daypart = "overnight"
            except Exception:
                daypart = ""
        ramp = profile_for_context(
            event_type=etype,
            daypart=daypart,
            ai_dj=(etype == "VOICE_TRACK" and daypart == "overnight"),
        )
        with SESSION.lock:
            SESSION.running = True
            SESSION.event_id = int(ev["id"])
            SESSION.started_at = time.time()
            SESSION.duration_ms = duration
            SESSION.title = ev["title"] or ""
            SESSION.artist = ev["artist"] or ""
            SESSION.event_type = etype
            SESSION.end_pulse_ms = pulse
            SESSION.intro_ms = intro
            SESSION.track_id = track_id
            SESSION.file_path = file_path
            SESSION.ramp_profile = str(ramp.get("id") or "default")

    def _start_event(self, conn, ev) -> EngineState:
        conn.execute(
            "UPDATE log_events SET status='COMMITTED' WHERE status='ON_AIR' AND id!=?",
            (ev["id"],),
        )
        conn.execute("UPDATE log_events SET status='ON_AIR' WHERE id=?", (ev["id"],))
        conn.commit()
        duration = _air_duration(ev)
        self._bind_session(ev, duration)
        self._state = EngineState(
            running=True,
            current_event_id=int(ev["id"]),
            current_title=ev["title"],
            current_artist=ev["artist"],
            position=int(ev["position"]),
            message=(
                f"ON AIR #{ev['position']} [{ev['event_type']}] "
                f"{ev['artist'] or ''} — {ev['title']}"
            ),
        )
        return self._state

    def _complete_current(self, conn, outcome: str = "PLAYED") -> Optional[dict]:
        with SESSION.lock:
            event_id = SESSION.event_id
            duration_ms = SESSION.duration_ms
        if not event_id:
            return None
        ev = conn.execute("SELECT * FROM log_events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            with SESSION.lock:
                SESSION.clear()
            return None
        status = "SKIPPED" if outcome == "SKIPPED" else "COMPLETED"
        conn.execute("UPDATE log_events SET status=? WHERE id=?", (status, event_id))
        played_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            """INSERT INTO as_played
               (log_event_id, track_id, played_at, scheduled_at, event_type, title, artist, duration_ms, outcome, engine)
               VALUES (?,?,?,?,?,?,?, ?,?, 'MockEngine')""",
            (
                ev["id"],
                ev["track_id"],
                played_at,
                ev["scheduled_at"],
                ev["event_type"],
                ev["title"],
                ev["artist"],
                duration_ms or ev["duration_ms"],
                outcome,
            ),
        )
        if ev["track_id"] and ev["event_type"] == "MUSIC" and outcome == "PLAYED":
            conn.execute(
                """UPDATE tracks SET last_played=?, play_count=play_count+1,
                   updated_at=datetime('now') WHERE id=?""",
                (played_at, ev["track_id"]),
            )
        conn.commit()
        with SESSION.lock:
            SESSION.clear()
        return dict(ev)

    def play(self) -> EngineState:
        conn = get_connection(self.db_path)
        did = self._daily_log_id(conn)
        if not did:
            conn.close()
            self._state.message = "no log"
            return self._state

        on_air = self._on_air_event(conn, did)
        if on_air:
            with SESSION.lock:
                needs_bind = (
                    SESSION.event_id != int(on_air["id"]) or SESSION.started_at is None
                )
            if needs_bind:
                self._bind_session(on_air, _air_duration(on_air))
            else:
                with SESSION.lock:
                    SESSION.running = True
            conn.close()
            self._state.running = True
            self._state.message = "playing"
            self._state.current_event_id = int(on_air["id"])
            self._state.current_title = on_air["title"]
            self._state.current_artist = on_air["artist"]
            self._state.position = int(on_air["position"])
            return self._state

        ev = self._next_event(conn, did)
        if not ev:
            conn.close()
            self._state.message = "log empty"
            return self._state
        st = self._start_event(conn, ev)
        conn.close()
        return st

    def stop(self) -> EngineState:
        with SESSION.lock:
            SESSION.running = False
            event_id = SESSION.event_id
            SESSION.clear()
            SESSION.running = False
        if event_id:
            conn = get_connection(self.db_path)
            conn.execute(
                "UPDATE log_events SET status='COMMITTED' WHERE id=? AND status='ON_AIR'",
                (event_id,),
            )
            conn.commit()
            conn.close()
        self._state.running = False
        self._state.message = "stopped"
        return self._state

    def skip(self) -> EngineState:
        conn = get_connection(self.db_path)
        did = self._daily_log_id(conn)
        if not did:
            conn.close()
            self._state.message = "no log"
            return self._state
        self._complete_current(conn, outcome="SKIPPED")
        if SESSION.event_id is None:
            ev = self._next_event(conn, did)
            if ev:
                conn.execute(
                    "UPDATE log_events SET status='SKIPPED' WHERE id=?", (ev["id"],)
                )
                conn.commit()
                self._state.message = f"skipped #{ev['position']} {ev['title']}"
        conn.close()
        return self.play()

    def step(self) -> EngineState:
        """Advance: complete current if any, then start next."""
        conn = get_connection(self.db_path)
        did = self._daily_log_id(conn)
        if not did:
            conn.close()
            self._state.message = "no daily log — generate-log first"
            return self._state
        self._complete_current(conn, outcome="PLAYED")
        conn.close()
        return self.play()

    def finish_if_due(self) -> bool:
        """Complete ON AIR cart on end-pulse (AUTO) or EOF; chain next if auto_advance."""
        with SESSION.lock:
            if SESSION.started_at is None or SESSION.event_id is None:
                return False
            timing = SESSION.timing()
            running = SESSION.running
            auto = SESSION.auto_advance
            due = bool(timing.get("pulse_due") or timing.get("finished"))
        if not due:
            return False
        conn = get_connection(self.db_path)
        self._complete_current(conn, outcome="PLAYED")
        conn.close()
        if running and auto:
            self.play()
        return True

    def status(self) -> EngineState:
        with SESSION.lock:
            self._state.running = SESSION.running
            self._state.current_event_id = SESSION.event_id
            self._state.current_title = SESSION.title
            self._state.current_artist = SESSION.artist
        return self._state

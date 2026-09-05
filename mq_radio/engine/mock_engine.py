"""MockEngine — Living Log playout with real ON-AIR hold for timers."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.engine.base import EngineState, PlayoutEngine
from mq_radio.engine.session import SESSION


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
            """SELECT * FROM log_events
               WHERE daily_log_id = ? AND status IN ('COMMITTED', 'DRAFT')
                 AND event_type != 'ETM'
               ORDER BY position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()

    def _on_air_event(self, conn, daily_log_id: int):
        return conn.execute(
            """SELECT * FROM log_events
               WHERE daily_log_id = ? AND status = 'ON_AIR'
               ORDER BY position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()

    def _start_event(self, conn, ev) -> EngineState:
        # Clear any stale ON_AIR rows
        conn.execute(
            "UPDATE log_events SET status='COMMITTED' WHERE status='ON_AIR' AND id!=?",
            (ev["id"],),
        )
        conn.execute("UPDATE log_events SET status='ON_AIR' WHERE id=?", (ev["id"],))
        conn.commit()
        duration = int(ev["duration_ms"] or 0)
        # Demo WAVs are short; give MUSIC carts a credible air timer floor for desk feel
        if (ev["event_type"] or "") == "MUSIC" and duration < 90_000:
            duration = max(duration, 180_000)  # 3:00 floor for music
        elif duration < 5_000:
            duration = max(duration, 8_000)

        with SESSION.lock:
            SESSION.running = True
            SESSION.event_id = int(ev["id"])
            SESSION.started_at = time.time()
            SESSION.duration_ms = duration
            SESSION.title = ev["title"] or ""
            SESSION.artist = ev["artist"] or ""
            SESSION.event_type = ev["event_type"] or ""

        self._state = EngineState(
            running=True,
            current_event_id=int(ev["id"]),
            current_title=ev["title"],
            current_artist=ev["artist"],
            position=int(ev["position"]),
            message=f"ON AIR #{ev['position']} [{ev['event_type']}] {ev['artist'] or ''} — {ev['title']}",
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
            # Resume / already playing
            with SESSION.lock:
                if SESSION.event_id != int(on_air["id"]) or SESSION.started_at is None:
                    SESSION.running = True
                    SESSION.event_id = int(on_air["id"])
                    SESSION.started_at = time.time()
                    dur = int(on_air["duration_ms"] or 0)
                    if (on_air["event_type"] or "") == "MUSIC" and dur < 90_000:
                        dur = 180_000
                    SESSION.duration_ms = dur
                    SESSION.title = on_air["title"] or ""
                    SESSION.artist = on_air["artist"] or ""
                    SESSION.event_type = on_air["event_type"] or ""
                else:
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
            # Keep ON_AIR row + start time frozen? For stop, freeze timer by clearing started_at offset —
            # simpler: leave event ON_AIR but pause by storing pause — for M1 stop clears to COMMITTED
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
        # If nothing was on air, skip next committed
        if SESSION.event_id is None:
            ev = self._next_event(conn, did)
            if ev:
                conn.execute("UPDATE log_events SET status='SKIPPED' WHERE id=?", (ev["id"],))
                conn.commit()
                self._state.message = f"skipped #{ev['position']} {ev['title']}"
        was_running = True
        with SESSION.lock:
            # after complete, decide whether to continue
            pass
        conn.close()
        # Auto-chain next cart after skip
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
        """Complete ON AIR cart when timer expires; start next if running. Returns True if advanced."""
        with SESSION.lock:
            timing_finished = (
                SESSION.started_at is not None
                and SESSION.duration_ms > 0
                and (time.time() - SESSION.started_at) * 1000 >= SESSION.duration_ms
            )
            running = SESSION.running
        if not timing_finished:
            return False
        conn = get_connection(self.db_path)
        self._complete_current(conn, outcome="PLAYED")
        conn.close()
        if running:
            self.play()
        return True

    def status(self) -> EngineState:
        with SESSION.lock:
            self._state.running = SESSION.running
            self._state.current_event_id = SESSION.event_id
            self._state.current_title = SESSION.title
            self._state.current_artist = SESSION.artist
        return self._state

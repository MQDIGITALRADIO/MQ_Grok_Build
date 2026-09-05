"""MockEngine — steps through committed Living Log without real audio I/O."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.engine.base import EngineState, PlayoutEngine


class MockEngine(PlayoutEngine):
    def __init__(self, log_date: str, db_path: Optional[Path] = None):
        self.log_date = log_date
        self.db_path = db_path
        self._state = EngineState(message="mock idle")
        self._running = False

    def _daily_log_id(self, conn) -> Optional[int]:
        row = conn.execute(
            "SELECT id FROM daily_logs WHERE log_date = ?", (self.log_date,)
        ).fetchone()
        return int(row["id"]) if row else None

    def _next_event(self, conn, daily_log_id: int):
        return conn.execute(
            """SELECT * FROM log_events
               WHERE daily_log_id = ? AND status IN ('COMMITTED', 'DRAFT')
               ORDER BY position LIMIT 1""",
            (daily_log_id,),
        ).fetchone()

    def play(self) -> EngineState:
        self._running = True
        self._state.running = True
        self._state.message = "playing"
        return self.step()

    def stop(self) -> EngineState:
        self._running = False
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
        ev = self._next_event(conn, did)
        if not ev:
            conn.close()
            self._state.message = "log empty"
            return self._state
        conn.execute(
            "UPDATE log_events SET status='SKIPPED' WHERE id=?", (ev["id"],)
        )
        conn.execute(
            """INSERT INTO as_played
               (log_event_id, track_id, played_at, scheduled_at, event_type, title, artist, duration_ms, outcome, engine)
               VALUES (?,?,datetime('now'),?,?,?,?,?,'SKIPPED','MockEngine')""",
            (
                ev["id"], ev["track_id"], ev["scheduled_at"], ev["event_type"],
                ev["title"], ev["artist"], ev["duration_ms"],
            ),
        )
        conn.commit()
        conn.close()
        self._state.message = f"skipped #{ev['position']} {ev['title']}"
        self._state.current_event_id = ev["id"]
        return self.step() if self._running else self.status()

    def step(self) -> EngineState:
        conn = get_connection(self.db_path)
        did = self._daily_log_id(conn)
        if not did:
            conn.close()
            self._state.message = "no daily log — generate-log first"
            return self._state

        ev = self._next_event(conn, did)
        if not ev:
            conn.close()
            self._state.running = False
            self._running = False
            self._state.message = "end of log"
            return self._state

        # Mark ON_AIR then immediately complete for mock step
        conn.execute("UPDATE log_events SET status='ON_AIR' WHERE id=?", (ev["id"],))
        conn.execute("UPDATE log_events SET status='COMPLETED' WHERE id=?", (ev["id"],))
        played_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            """INSERT INTO as_played
               (log_event_id, track_id, played_at, scheduled_at, event_type, title, artist, duration_ms, outcome, engine)
               VALUES (?,?,?,?,?,?,?,?,'PLAYED','MockEngine')""",
            (
                ev["id"], ev["track_id"], played_at, ev["scheduled_at"],
                ev["event_type"], ev["title"], ev["artist"], ev["duration_ms"],
            ),
        )
        if ev["track_id"] and ev["event_type"] == "MUSIC":
            conn.execute(
                """UPDATE tracks SET last_played=?, play_count=play_count+1,
                   updated_at=datetime('now') WHERE id=?""",
                (played_at, ev["track_id"]),
            )
        conn.commit()
        conn.close()

        self._state = EngineState(
            running=self._running,
            current_event_id=int(ev["id"]),
            current_title=ev["title"],
            current_artist=ev["artist"],
            position=int(ev["position"]),
            message=f"played #{ev['position']} [{ev['event_type']}] {ev['artist'] or ''} — {ev['title']}",
        )
        return self._state

    def status(self) -> EngineState:
        self._state.running = self._running
        return self._state

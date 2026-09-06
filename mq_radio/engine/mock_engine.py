"""MockEngine — Living Log playout with overlapping dual-deck segue.

AUTO honors end-pulse (ingest outro_ms): starts the next cart on the other
deck while the current cart fades (classic overlapping segue), using Segue
Editor markers (out/VT/in, duck, crossfade) when present.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mq_radio.db.connection import get_connection
from mq_radio.engine.base import EngineState, PlayoutEngine
from mq_radio.engine.session import FadingDeck, SESSION
from mq_radio.production.ramps import profile_for_context
from mq_radio.segue.service import resolve_overlap_params


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

    def _neighbor_event_types(self, conn, ev) -> tuple[str, str]:
        """Return (prev_type, next_type) by position within the same daily log."""
        try:
            daily_log_id = int(ev["daily_log_id"])
            pos = int(ev["position"])
        except Exception:
            return "", ""
        prev = conn.execute(
            """SELECT event_type FROM log_events
               WHERE daily_log_id=? AND position < ? AND event_type != 'ETM'
               ORDER BY position DESC LIMIT 1""",
            (daily_log_id, pos),
        ).fetchone()
        nxt = conn.execute(
            """SELECT event_type FROM log_events
               WHERE daily_log_id=? AND position > ? AND event_type != 'ETM'
               ORDER BY position ASC LIMIT 1""",
            (daily_log_id, pos),
        ).fetchone()
        return (
            (prev["event_type"] or "") if prev else "",
            (nxt["event_type"] or "") if nxt else "",
        )

    def _bind_session(
        self,
        ev,
        duration: int,
        *,
        keep_overlap: bool = False,
        neighbor_event_type: str = "",
        near_vt: bool = False,
    ) -> None:
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
        mode = "AUTO"
        with SESSION.lock:
            mode = SESSION.playout_mode or "AUTO"
        ramp = profile_for_context(
            event_type=etype,
            daypart=daypart,
            ai_dj=(etype == "VOICE_TRACK" and daypart == "overnight"),
            near_vt=near_vt or etype == "VOICE_TRACK",
            neighbor_event_type=neighbor_event_type,
            playout_mode=mode,
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
            SESSION.assist_go_ready = False
            if not keep_overlap:
                SESSION.clear_overlap()

    def _snapshot_fading(self) -> FadingDeck:
        with SESSION.lock:
            timing = SESSION.timing()
            return FadingDeck(
                event_id=SESSION.event_id,
                title=SESSION.title,
                artist=SESSION.artist,
                event_type=SESSION.event_type,
                duration_ms=SESSION.duration_ms,
                started_at=SESSION.started_at,
                elapsed_at_fade=int(timing.get("elapsed_ms") or 0),
                end_pulse_ms=SESSION.end_pulse_ms,
                intro_ms=SESSION.intro_ms,
                track_id=SESSION.track_id,
                file_path=SESSION.file_path,
                ramp_profile=SESSION.ramp_profile,
                deck=SESSION.active_deck,
            )

    def _start_event(self, conn, ev, *, keep_overlap: bool = False) -> EngineState:
        conn.execute(
            "UPDATE log_events SET status='COMMITTED' WHERE status='ON_AIR' AND id!=?",
            (ev["id"],),
        )
        conn.execute("UPDATE log_events SET status='ON_AIR' WHERE id=?", (ev["id"],))
        conn.commit()
        duration = _air_duration(ev)
        prev_t, next_t = self._neighbor_event_types(conn, ev)
        neighbor = next_t or prev_t
        near_vt = "VOICE_TRACK" in (prev_t, next_t, ev["event_type"] or "")
        self._bind_session(
            ev,
            duration,
            keep_overlap=keep_overlap,
            neighbor_event_type=neighbor,
            near_vt=near_vt,
        )
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

    def _complete_current(self, conn, outcome: str = "PLAYED", *, clear_session: bool = True) -> Optional[dict]:
        with SESSION.lock:
            event_id = SESSION.event_id
            duration_ms = SESSION.duration_ms
        if not event_id:
            return None
        ev = conn.execute("SELECT * FROM log_events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            with SESSION.lock:
                if clear_session:
                    SESSION.clear()
            return None
        status = "SKIPPED" if outcome == "SKIPPED" else "COMPLETED"
        conn.execute("UPDATE log_events SET status=? WHERE id=?", (status, event_id))
        played_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
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
        if clear_session:
            with SESSION.lock:
                SESSION.clear()
        return dict(ev)

    def _clear_fade_if_due(self) -> None:
        with SESSION.lock:
            if SESSION.overlap_active and SESSION.fade_due():
                SESSION.clear_overlap()

    def play(self) -> EngineState:
        self._clear_fade_if_due()
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
            SESSION.oneshot = None
            SESSION.running = False
            SESSION.active_deck = "A"
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
        with SESSION.lock:
            SESSION.clear_overlap()
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
        """Advance with overlapping segue when a next cart exists."""
        return self.advance_with_overlap(force=True)

    def advance_with_overlap(self, *, force: bool = False) -> EngineState:
        """Complete current (as-played), start next on the other deck, keep fade.

        force=True: operator NEXT / ASSIST GO / step — always advance if possible.
        force=False: only when pulse_due/finished (AUTO path).
        """
        self._clear_fade_if_due()
        conn = get_connection(self.db_path)
        did = self._daily_log_id(conn)
        if not did:
            conn.close()
            self._state.message = "no daily log — generate-log first"
            return self._state

        with SESSION.lock:
            has_current = SESSION.event_id is not None and SESSION.started_at is not None
            timing = SESSION.timing() if has_current else {}
            running = SESSION.running
            auto = SESSION.auto_advance
            mode = SESSION.playout_mode
            due = bool(timing.get("pulse_due") or timing.get("finished"))
            from_id = SESSION.event_id
            end_pulse = SESSION.end_pulse_ms
            from_outro = SESSION.end_pulse_ms
            outgoing_deck = SESSION.active_deck

        if has_current and not force and not due:
            conn.close()
            return self.status()

        # ASSIST/LIVE without force: arm GO instead of chaining
        if has_current and not force and not auto and mode in ("ASSIST", "LIVE"):
            if due:
                with SESSION.lock:
                    SESSION.assist_go_ready = True
                # Still complete+hold? Classic ASSIST holds — mark assist ready only
                conn.close()
                self._state.message = "ASSIST GO — next armed"
                return self.status()
            conn.close()
            return self.status()

        next_ev = self._next_event(conn, did)
        if not has_current:
            conn.close()
            return self.play()

        if not next_ev:
            # Nothing to overlap onto — finish cleanly
            self._complete_current(conn, outcome="PLAYED")
            with SESSION.lock:
                SESSION.clear_overlap()
            conn.close()
            self._state.running = False
            self._state.message = "log empty"
            return self._state

        # Resolve Segue Editor markers / defaults
        to_intro = int(next_ev["intro_ms"] or 0) if "intro_ms" in next_ev.keys() else 0
        params = resolve_overlap_params(
            from_id,
            int(next_ev["id"]),
            end_pulse_ms=int(end_pulse or 0),
            from_outro_ms=int(from_outro or 0),
            to_intro_ms=to_intro,
            next_event_type=next_ev["event_type"] or "",
            db_path=self.db_path,
        )

        fading = self._snapshot_fading()
        # Complete outgoing without clearing session yet
        self._complete_current(conn, outcome="PLAYED", clear_session=False)

        # Flip program deck to the other side and start incoming
        with SESSION.lock:
            SESSION.flip_deck()
            incoming_deck = SESSION.active_deck
            SESSION.fading = fading
            SESSION.overlap_active = True
            SESSION.assist_go_ready = False
            SESSION.segue = {
                **params,
                "started_at": time.time(),
                "outgoing_deck": outgoing_deck,
                "incoming_deck": incoming_deck,
            }

        st = self._start_event(conn, next_ev, keep_overlap=True)
        # Re-apply overlap after _start_event keep_overlap path
        with SESSION.lock:
            SESSION.fading = fading
            SESSION.overlap_active = True
            SESSION.segue = {
                **params,
                "started_at": time.time(),
                "outgoing_deck": outgoing_deck,
                "incoming_deck": SESSION.active_deck,
            }
            st.message = (
                f"SEGUE {outgoing_deck}→{SESSION.active_deck} "
                f"xfade {params['crossfade_ms']}ms · {st.message}"
            )
        conn.close()
        if not running and not force:
            pass
        return st

    def finish_if_due(self) -> bool:
        """Complete ON AIR cart on end-pulse (AUTO) or EOF; overlapping chain if auto_advance."""
        self._clear_fade_if_due()
        with SESSION.lock:
            if SESSION.started_at is None or SESSION.event_id is None:
                return False
            timing = SESSION.timing()
            running = SESSION.running
            auto = SESSION.auto_advance
            mode = SESSION.playout_mode
            due = bool(timing.get("pulse_due") or timing.get("finished"))
        if not due:
            return False

        if not auto and mode in ("ASSIST", "LIVE"):
            # Hold after pulse; arm GO for operator overlapping advance
            with SESSION.lock:
                SESSION.assist_go_ready = True
            # If finished (EOF), still complete so we don't stick forever — but don't auto chain
            if timing.get("finished"):
                conn = get_connection(self.db_path)
                self._complete_current(conn, outcome="PLAYED")
                conn.close()
            return True

        if running and auto:
            self.advance_with_overlap(force=False)
            return True

        # Fallback: complete without chain
        conn = get_connection(self.db_path)
        self._complete_current(conn, outcome="PLAYED")
        conn.close()
        return True

    def inject_oneshot(
        self,
        *,
        label: str,
        path: Optional[str] = None,
        track_id: Optional[int] = None,
        event_type: str = "SWEEPER",
        duration_ms: int = 0,
        mode: str = "over_program",
        log_date: Optional[str] = None,
    ) -> dict:
        """Inject a hotkey cart into the play path without breaking Living Log AUTO.

        mode:
          - over_program: transient one-shot layered over current program (default)
          - queue_next: insert a MANUAL log event after the ON AIR cart (AUTO still owns chain)
        """
        mode = (mode or "over_program").strip().lower().replace("-", "_")
        if mode in ("over", "oneshot", "fire"):
            mode = "over_program"
        if mode in ("queue", "next", "insert"):
            mode = "queue_next"
        if mode not in ("over_program", "queue_next"):
            mode = "over_program"

        label = (label or "Hotkey").strip() or "Hotkey"
        etype = (event_type or "SWEEPER").upper()
        if etype in ("VT", "VOICE TRACK"):
            etype = "VOICE_TRACK"
        file_path = str(path) if path else ""
        dur = max(0, int(duration_ms or 0))
        if track_id is not None and (not file_path or dur <= 0):
            conn = get_connection(self.db_path)
            row = conn.execute(
                "SELECT file_path, duration_ms, event_type, title FROM tracks WHERE id=?",
                (int(track_id),),
            ).fetchone()
            conn.close()
            if row:
                file_path = file_path or (row["file_path"] or "")
                if dur <= 0:
                    dur = int(row["duration_ms"] or 0)
                if not event_type or event_type == "SWEEPER":
                    etype = (row["event_type"] or etype).upper()
                if label == "Hotkey" and row["title"]:
                    label = row["title"]
        if dur <= 0:
            dur = 8000  # desk-visible default for unknown one-shots

        if mode == "queue_next":
            from mq_radio.living_log.service import insert_event

            day = log_date or self.log_date
            conn = get_connection(self.db_path)
            did = self._daily_log_id(conn)
            after_pos = -1
            on_air = self._on_air_event(conn, did) if did else None
            if on_air:
                after_pos = int(on_air["position"])
            else:
                with SESSION.lock:
                    eid = SESSION.event_id
                if eid:
                    row = conn.execute(
                        "SELECT position FROM log_events WHERE id=?", (eid,)
                    ).fetchone()
                    if row:
                        after_pos = int(row["position"])
            conn.close()
            inserted = insert_event(
                day,
                after_pos,
                {
                    "track_id": track_id,
                    "event_type": etype,
                    "title": label,
                    "artist": "Hotkey",
                    "duration_ms": dur,
                    "notes": f"[HOTKEY INJECT queue_next] {file_path}".strip(),
                },
                db_path=self.db_path,
            )
            if not inserted.get("ok"):
                return {
                    "ok": False,
                    "mode": mode,
                    "error": inserted.get("error") or "queue_next insert failed",
                }
            msg = (
                f"HOTKEY QUEUED NEXT: {label} "
                f"(after pos {after_pos} → event {inserted.get('event_id')}) — AUTO intact"
            )
            self._state.message = msg
            return {
                "ok": True,
                "mode": mode,
                "injected": True,
                "label": label,
                "path": file_path or None,
                "track_id": track_id,
                "event_type": etype,
                "duration_ms": dur,
                "log_event_id": inserted.get("event_id"),
                "after_position": after_pos,
                "message": msg,
            }

        # over_program — transient session oneshot; Living Log untouched
        shot = {
            "label": label,
            "path": file_path or None,
            "track_id": track_id,
            "event_type": etype,
            "duration_ms": dur,
            "mode": "over_program",
            "started_at": time.time(),
        }
        with SESSION.lock:
            SESSION.oneshot = shot
        msg = f"HOTKEY OVER PROGRAM: {label}" + (f" · {file_path}" if file_path else "")
        self._state.message = msg
        return {
            "ok": True,
            "mode": "over_program",
            "injected": True,
            "label": label,
            "path": file_path or None,
            "track_id": track_id,
            "event_type": etype,
            "duration_ms": dur,
            "message": msg,
            "oneshot": dict(shot),
        }

    def status(self) -> EngineState:
        self._clear_fade_if_due()
        with SESSION.lock:
            self._state.running = SESSION.running
            self._state.current_event_id = SESSION.event_id
            self._state.current_title = SESSION.title
            self._state.current_artist = SESSION.artist
        return self._state

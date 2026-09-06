"""Process-level playout session — holds ON AIR start time for elapsed/remaining.

Supports overlapping dual-deck segue: program deck holds the incoming/current
cart while a fading deck snapshot keeps the outgoing cart audible during
crossfade.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


DEFAULT_CROSSFADE_MS = 1500


@dataclass
class FadingDeck:
    """Outgoing cart still audible during an overlapping segue."""

    event_id: Optional[int] = None
    title: str = ""
    artist: str = ""
    event_type: str = ""
    duration_ms: int = 0
    started_at: Optional[float] = None
    elapsed_at_fade: int = 0
    end_pulse_ms: int = 0
    intro_ms: int = 0
    track_id: Optional[int] = None
    file_path: str = ""
    ramp_profile: str = "default"
    deck: str = "A"  # UI deck letter holding the fade
    playable_event: Optional[dict] = None

    def to_dict(self) -> dict:
        now = time.time()
        elapsed = int(self.elapsed_at_fade or 0)
        if self.started_at is not None:
            # Continue counting from when fade began using wall clock
            fade_elapsed = int(max(0, (now - self.started_at) * 1000))
            elapsed = max(elapsed, fade_elapsed)
        dur = max(0, int(self.duration_ms or 0))
        remaining = max(0, dur - elapsed)
        return {
            "event_id": self.event_id,
            "title": self.title,
            "artist": self.artist,
            "event_type": self.event_type,
            "duration_ms": dur,
            "elapsed_ms": elapsed,
            "remaining_ms": remaining,
            "end_pulse_ms": self.end_pulse_ms,
            "intro_ms": self.intro_ms,
            "track_id": self.track_id,
            "file_path": self.file_path or "",
            "ramp_profile": self.ramp_profile,
            "deck": self.deck,
            "role": "fading",
            "playable_url": None,  # filled by API enrich
        }


@dataclass
class PlayoutSession:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    event_id: Optional[int] = None
    started_at: Optional[float] = None  # time.time()
    duration_ms: int = 0
    title: str = ""
    artist: str = ""
    event_type: str = ""
    # End-pulse (from ingest outro_ms): AUTO fires next when remaining <= end_pulse_ms
    end_pulse_ms: int = 0
    intro_ms: int = 0
    track_id: Optional[int] = None
    file_path: str = ""
    # AUTO advances on pulse/EOF; ASSIST/LIVE hold after cart until operator
    auto_advance: bool = True
    playout_mode: str = "AUTO"
    # Volume ramp profile id applied for this cart
    ramp_profile: str = "default"

    # Dual-deck: which UI deck is program (ON AIR primary)
    active_deck: str = "A"
    # Overlapping segue state
    overlap_active: bool = False
    fading: Optional[FadingDeck] = None
    segue: dict = field(default_factory=dict)
    # ASSIST: pulse armed next — operator GO starts overlapping advance
    assist_go_ready: bool = False
    # Hotkey one-shot inject (over program) — does NOT alter Living Log AUTO chain
    oneshot: Optional[dict] = None

    def clear(self) -> None:
        self.running = False
        self.event_id = None
        self.started_at = None
        self.duration_ms = 0
        self.title = ""
        self.artist = ""
        self.event_type = ""
        self.end_pulse_ms = 0
        self.intro_ms = 0
        self.track_id = None
        self.file_path = ""
        self.ramp_profile = "default"
        self.overlap_active = False
        self.fading = None
        self.segue = {}
        self.assist_go_ready = False
        # oneshot is intentionally NOT cleared on cart advance — it lives over program
        # keep active_deck so A/B flip persists across carts

    def clear_overlap(self) -> None:
        self.overlap_active = False
        self.fading = None
        self.segue = {}

    def flip_deck(self) -> str:
        self.active_deck = "B" if self.active_deck == "A" else "A"
        return self.active_deck

    def timing(self) -> dict:
        """Elapsed/remaining + end-pulse + ASSIST talk-up (VOCALS IN) countdown fields."""
        intro = int(self.intro_ms or 0)
        etype = (self.event_type or "").upper()
        if self.started_at is None or self.event_id is None:
            return {
                "playing": False,
                "elapsed_ms": 0,
                "remaining_ms": 0,
                "duration_ms": self.duration_ms or 0,
                "progress": 0.0,
                "end_pulse_ms": self.end_pulse_ms or 0,
                "intro_ms": intro,
                "in_end_pulse": False,
                "pulse_due": False,
                "in_intro": False,
                "talk_up_remaining_ms": 0,
                "vocals_in": False,
                "event_type": etype,
                "active_deck": self.active_deck,
                "overlap_active": self.overlap_active,
                "assist_go_ready": self.assist_go_ready,
            }
        elapsed = int(max(0, (time.time() - self.started_at) * 1000))
        dur = max(0, int(self.duration_ms or 0))
        remaining = max(0, dur - elapsed)
        progress = 0.0 if dur <= 0 else min(1.0, elapsed / dur)
        pulse = max(0, int(self.end_pulse_ms or 0))
        # Pulse fires when we enter the end-pulse window (remaining <= pulse)
        in_pulse = pulse > 0 and remaining <= pulse and dur > 0
        pulse_due = False
        if dur > 0:
            if pulse > 0:
                pulse_due = elapsed >= max(0, dur - pulse)
            else:
                pulse_due = elapsed >= dur
        # Talk-up / VOCALS IN: remaining intro window (desk shows in ASSIST/LIVE)
        in_intro = intro > 0 and elapsed < intro
        talk_up_remaining_ms = max(0, intro - elapsed) if in_intro else 0
        vocals_in = intro > 0 and elapsed >= intro
        return {
            "playing": True,
            "elapsed_ms": elapsed,
            "remaining_ms": remaining,
            "duration_ms": dur,
            "progress": progress,
            "finished": dur > 0 and elapsed >= dur,
            "end_pulse_ms": pulse,
            "intro_ms": intro,
            "in_end_pulse": in_pulse,
            "pulse_due": pulse_due,
            "in_intro": in_intro,
            "talk_up_remaining_ms": talk_up_remaining_ms,
            "vocals_in": vocals_in,
            "event_type": etype,
            "track_id": self.track_id,
            "file_path": self.file_path or "",
            "ramp_profile": self.ramp_profile,
            "auto_advance": self.auto_advance,
            "playout_mode": self.playout_mode,
            "active_deck": self.active_deck,
            "overlap_active": self.overlap_active,
            "assist_go_ready": self.assist_go_ready,
        }

    def decks_snapshot(self) -> dict[str, Any]:
        """Expose deck A/B for UI: program + optional fading overlap."""
        timing = self.timing()
        program = None
        if self.event_id is not None:
            program = {
                "event_id": self.event_id,
                "title": self.title,
                "artist": self.artist,
                "event_type": self.event_type,
                "duration_ms": self.duration_ms,
                "elapsed_ms": timing.get("elapsed_ms", 0),
                "remaining_ms": timing.get("remaining_ms", 0),
                "end_pulse_ms": self.end_pulse_ms,
                "intro_ms": self.intro_ms,
                "track_id": self.track_id,
                "file_path": self.file_path or "",
                "ramp_profile": self.ramp_profile,
                "deck": self.active_deck,
                "role": "program",
                "playing": bool(timing.get("playing")),
            }
        fading = self.fading.to_dict() if self.fading and self.overlap_active else None
        fading_letter = (fading or {}).get("deck")
        other = "B" if self.active_deck == "A" else "A"
        a = program if self.active_deck == "A" else (fading if fading_letter == "A" else None)
        b = program if self.active_deck == "B" else (fading if fading_letter == "B" else None)
        # If no fading, other deck is empty (UI fills NEXT from upcoming)
        return {
            "active": self.active_deck,
            "overlap_active": self.overlap_active,
            "assist_go_ready": self.assist_go_ready,
            "a": a,
            "b": b,
            "program": program,
            "fading": fading,
            "other_deck": other,
            "segue": dict(self.segue or {}),
        }

    def oneshot_snapshot(self) -> Optional[dict]:
        """Active hotkey one-shot over program, or None if idle/expired."""
        shot = self.oneshot
        if not shot:
            return None
        started = shot.get("started_at")
        dur = int(shot.get("duration_ms") or 0)
        if started is None:
            return dict(shot)
        elapsed = int(max(0, (time.time() - float(started)) * 1000))
        if dur > 0 and elapsed >= dur:
            self.oneshot = None
            return None
        out = dict(shot)
        out["elapsed_ms"] = elapsed
        out["remaining_ms"] = max(0, dur - elapsed) if dur else None
        out["active"] = True
        return out

    def fade_due(self) -> bool:
        """True when overlapping fade window has elapsed."""
        if not self.overlap_active or not self.segue:
            return False
        started = self.segue.get("started_at")
        ms = int(self.segue.get("crossfade_ms") or 0)
        if started is None:
            return True
        return (time.time() - float(started)) * 1000 >= max(0, ms)


SESSION = PlayoutSession()

"""Process-level playout session — holds ON AIR start time for elapsed/remaining."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


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

    def timing(self) -> dict:
        if self.started_at is None or self.event_id is None:
            return {
                "playing": False,
                "elapsed_ms": 0,
                "remaining_ms": 0,
                "duration_ms": self.duration_ms or 0,
                "progress": 0.0,
                "end_pulse_ms": self.end_pulse_ms or 0,
                "intro_ms": self.intro_ms or 0,
                "in_end_pulse": False,
                "pulse_due": False,
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
        return {
            "playing": True,
            "elapsed_ms": elapsed,
            "remaining_ms": remaining,
            "duration_ms": dur,
            "progress": progress,
            "finished": dur > 0 and elapsed >= dur,
            "end_pulse_ms": pulse,
            "intro_ms": int(self.intro_ms or 0),
            "in_end_pulse": in_pulse,
            "pulse_due": pulse_due,
            "track_id": self.track_id,
            "file_path": self.file_path or "",
            "ramp_profile": self.ramp_profile,
            "auto_advance": self.auto_advance,
            "playout_mode": self.playout_mode,
        }


SESSION = PlayoutSession()

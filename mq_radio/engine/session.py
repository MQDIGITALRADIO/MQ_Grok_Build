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

    def clear(self) -> None:
        self.event_id = None
        self.started_at = None
        self.duration_ms = 0
        self.title = ""
        self.artist = ""
        self.event_type = ""

    def timing(self) -> dict:
        if self.started_at is None or self.event_id is None:
            return {
                "playing": False,
                "elapsed_ms": 0,
                "remaining_ms": 0,
                "duration_ms": self.duration_ms or 0,
                "progress": 0.0,
            }
        elapsed = int(max(0, (time.time() - self.started_at) * 1000))
        dur = max(0, int(self.duration_ms or 0))
        remaining = max(0, dur - elapsed)
        progress = 0.0 if dur <= 0 else min(1.0, elapsed / dur)
        return {
            "playing": True,
            "elapsed_ms": elapsed,
            "remaining_ms": remaining,
            "duration_ms": dur,
            "progress": progress,
            "finished": dur > 0 and elapsed >= dur,
        }


SESSION = PlayoutSession()

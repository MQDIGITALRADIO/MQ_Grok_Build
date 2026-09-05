"""Playout engine adapter interface — UI crash ≠ station dead air."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EngineState:
    running: bool = False
    current_event_id: Optional[int] = None
    current_title: Optional[str] = None
    current_artist: Optional[str] = None
    position: Optional[int] = None
    message: str = "idle"


class PlayoutEngine(ABC):
    """Background playout service contract (Mock + Liquidsoap stub)."""

    @abstractmethod
    def play(self) -> EngineState: ...

    @abstractmethod
    def stop(self) -> EngineState: ...

    @abstractmethod
    def skip(self) -> EngineState: ...

    @abstractmethod
    def step(self) -> EngineState:
        """Advance one committed log event (as-played)."""

    @abstractmethod
    def status(self) -> EngineState: ...

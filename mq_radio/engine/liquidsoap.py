"""LiquidsoapEngine stub — real playout adapter to be wired in later milestones."""

from __future__ import annotations

from mq_radio.engine.base import EngineState, PlayoutEngine


class LiquidsoapEngine(PlayoutEngine):
    """
    Stub for Liquidsoap / Telnet / Harbor integration.
    MQ Engine runs as a background service independent of the control UI.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 1234):
        self.host = host
        self.port = port
        self._state = EngineState(
            message=f"LiquidsoapEngine stub — not connected ({host}:{port})"
        )

    def play(self) -> EngineState:
        self._state.message = "LiquidsoapEngine.play() stub — wire telnet/harbor in M2+"
        self._state.running = False
        return self._state

    def stop(self) -> EngineState:
        self._state.message = "LiquidsoapEngine.stop() stub"
        self._state.running = False
        return self._state

    def skip(self) -> EngineState:
        self._state.message = "LiquidsoapEngine.skip() stub"
        return self._state

    def step(self) -> EngineState:
        self._state.message = "LiquidsoapEngine.step() stub — no liquidsoap process"
        return self._state

    def status(self) -> EngineState:
        return self._state

"""LiquidsoapEngine — Master Control adapter stub (no live Harbor yet).

Uses ``mq_radio.production.master_control`` for binary probe, dry-run, and
honest start/stop failures. Never claims a live Telnet/Harbor graph.
"""

from __future__ import annotations

from typing import Any, Optional

from mq_radio.engine.base import EngineState, PlayoutEngine
from mq_radio.production import master_control as mc


class LiquidsoapEngine(PlayoutEngine):
    """
    Stub for Liquidsoap / Telnet / Harbor integration.

    ``play`` / ``start`` fail clearly when the binary is missing, and still
    refuse to fake a live graph when the binary is present. MQ Engine desk
    playout continues via MockEngine / browser On-Air until this is wired.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1234,
        *,
        harbor_port: int = 8005,
        binary: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.harbor_port = harbor_port
        self.binary = binary
        self._running = False
        self._last_start: Optional[dict[str, Any]] = None
        bin_path = mc.resolve_liquidsoap_binary(explicit=binary)
        if bin_path:
            msg = (
                f"LiquidsoapEngine — binary present ({bin_path}), "
                f"Harbor/Telnet not wired ({host}:{port}, harbor {harbor_port})"
            )
        else:
            msg = (
                f"LiquidsoapEngine — liquidsoap binary missing "
                f"(telnet target {host}:{port}; install: brew install liquidsoap)"
            )
        self._state = EngineState(message=msg, running=False)

    def play(self) -> EngineState:
        return self.start()

    def start(self) -> EngineState:
        result = mc.start_stub(binary=self.binary)
        self._last_start = result
        self._running = False
        self._state.running = False
        self._state.message = result.get("operator_message") or result.get("error") or (
            "Master Control start refused"
        )
        return self._state

    def stop(self) -> EngineState:
        result = mc.stop_stub()
        self._running = False
        self._state.running = False
        self._state.message = result.get("operator_message") or "Master Control not running"
        return self._state

    def skip(self) -> EngineState:
        self._state.message = (
            "LiquidsoapEngine.skip() unavailable — live Harbor graph not wired"
        )
        return self._state

    def step(self) -> EngineState:
        probe = mc.probe_liquidsoap_version(
            mc.resolve_liquidsoap_binary(explicit=self.binary)
        )
        if not probe.get("available"):
            self._state.message = (
                "LiquidsoapEngine.step() — no liquidsoap process "
                f"({probe.get('error') or 'binary missing'})"
            )
        else:
            self._state.message = (
                "LiquidsoapEngine.step() — binary present but no live graph "
                f"({probe.get('version') or probe.get('binary')})"
            )
        self._state.running = False
        return self._state

    def status(self) -> EngineState:
        return self._state

    def operator_status(self) -> dict[str, Any]:
        """Rich status for Settings / API (not the PlayoutEngine state)."""
        base = mc.operator_status()
        base["telnet"] = {"host": self.host, "port": self.port, "wired": False}
        base["harbor"] = {"port": self.harbor_port, "wired": False}
        base["engine_running"] = False
        base["last_start"] = self._last_start
        return base

    def dry_run(self) -> dict[str, Any]:
        return mc.dry_run(binary=self.binary)

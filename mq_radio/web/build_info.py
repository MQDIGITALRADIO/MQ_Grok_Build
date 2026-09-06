"""Desktop/market build label for the On-Air titlebar.

Packaging (Electron) is the market version operators see (0.1.4).
Python package version may differ; this module is intentionally packaging-aligned.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from typing import Any

# Align with desktop/package.json — what operators download
DESKTOP_VERSION = "0.1.4"


@lru_cache(maxsize=1)
def build_sha() -> str:
    """Short git SHA, env override, or ``dev`` when unavailable (frozen DMG)."""
    for key in ("MQ_RADIO_BUILD_SHA", "GITHUB_SHA"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw[:7]
    try:
        from mq_radio.config import ROOT

        out = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        sha = out.decode("utf-8", errors="replace").strip()
        if sha:
            return sha[:7]
    except Exception:
        pass
    return "dev"


def version_payload() -> dict[str, Any]:
    sha = build_sha()
    return {
        "version": DESKTOP_VERSION,
        "sha": sha,
        "label": f"{DESKTOP_VERSION} · {sha}",
    }

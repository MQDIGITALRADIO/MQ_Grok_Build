"""Desktop entry point for the Electron-wrapped Mac app.

Bootstraps a demo station on first run, then serves the On-Air UI.
Designed to be frozen with PyInstaller as MQRadioEngine.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path


def _configure_paths() -> Path:
    data = os.environ.get("MQ_RADIO_DATA_DIR")
    if data:
        from mq_radio.config import apply_data_dir

        apply_data_dir(data)
    # Ensure migrations resolve from the frozen bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        import mq_radio.config as cfg

        mig = Path(sys._MEIPASS) / "migrations"
        if mig.is_dir():
            cfg.MIGRATIONS_DIR = mig
        cfg.ROOT = Path(sys._MEIPASS)

    from mq_radio.config import DB_PATH

    return Path(DB_PATH)


def bootstrap_if_needed(db_path: Path) -> None:
    """First launch: init DB, seed demo library, generate today's Living Log."""
    if db_path.exists() and db_path.stat().st_size > 0:
        return

    from mq_radio.db.connection import init_db
    from mq_radio.music_director.seed import seed_demo
    from mq_radio.scheduler.generator import generate_log

    print("[MQ Radio] First run — initializing demo station…", flush=True)
    init_db(db_path)
    seed_demo(db_path)
    generate_log(date.today().isoformat(), db_path=db_path)
    print("[MQ Radio] Demo ready.", flush=True)


def main() -> int:
    host = os.environ.get("MQ_RADIO_HOST", "127.0.0.1")
    port = int(os.environ.get("MQ_RADIO_PORT", "8080"))
    db_path = _configure_paths()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    bootstrap_if_needed(db_path)

    from mq_radio.web.app import run_server

    run_server(host=host, port=port, db_path=db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

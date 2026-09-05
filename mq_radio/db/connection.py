"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from mq_radio.config import DATA_DIR, DB_PATH, MIGRATIONS_DIR


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[Path] = None) -> Path:
    """Apply migrations and return DB path."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    try:
        applied = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchall()
        }
        if not applied:
            # bootstrap — migrations table created by 001
            pass
        else:
            pass

        import mq_radio.config as _cfg
        migrations = sorted(_cfg.MIGRATIONS_DIR.glob("*.sql"))
        for mig in migrations:
            version = mig.stem
            # ensure migrations table exists first via running file
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if existing:
                done = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if done:
                    continue
            sql = mig.read_text(encoding="utf-8")
            conn.executescript(sql)
            # record after script (001 creates the table)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
            conn.commit()
    finally:
        conn.close()
    return path


def fetchall(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))


def fetchone(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchone()

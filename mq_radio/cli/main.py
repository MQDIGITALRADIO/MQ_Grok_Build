"""MQ Radio Automation CLI."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from mq_radio.config import DB_PATH
from mq_radio.db.connection import init_db
from mq_radio.engine.mock_engine import MockEngine
from mq_radio.library.scanner import scan_directory
from mq_radio.living_log.service import list_events
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.generator import generate_log


def cmd_init_db(args: argparse.Namespace) -> int:
    path = init_db(Path(args.db) if args.db else None)
    print(f"Database initialized: {path}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    n = scan_directory(
        Path(args.path) if args.path else None,
        db_path=Path(args.db) if args.db else None,
        category_code=args.category,
    )
    print(f"Scanned/upserted {n} audio file(s)")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    result = seed_demo(Path(args.db) if args.db else None)
    print(json.dumps(result, indent=2))
    return 0


def cmd_generate_log(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    log_date = args.date or date.today().isoformat()
    result = generate_log(
        log_date,
        db_path=Path(args.db) if args.db else None,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_show_log(args: argparse.Namespace) -> int:
    log_date = args.date or date.today().isoformat()
    events = list_events(log_date, db_path=Path(args.db) if args.db else None, limit=args.limit)
    if not events:
        print(f"No log events for {log_date}")
        return 1
    print(f"Living Log {log_date} — {len(events)} event(s) shown")
    print(f"{'POS':>4}  {'TIME':<19}  {'TYPE':<12}  {'CHAIN':<7}  {'ARTIST':<22}  TITLE")
    print("-" * 100)
    for e in events:
        artist = (e.get("artist") or "")[:22]
        title = (e.get("title") or "")[:40]
        print(
            f"{e['position']:4d}  {e['scheduled_at']:<19}  {e['event_type']:<12}  "
            f"{e['chain_mode']:<7}  {artist:<22}  {title}"
        )
    return 0


def cmd_engine_step(args: argparse.Namespace) -> int:
    log_date = args.date or date.today().isoformat()
    engine = MockEngine(log_date, db_path=Path(args.db) if args.db else None)
    if args.action == "play":
        st = engine.play()
    elif args.action == "stop":
        st = engine.stop()
    elif args.action == "skip":
        engine._running = True
        st = engine.skip()
    else:
        st = engine.step()
    print(f"[{st.message}] running={st.running} pos={st.position} "
          f"{st.current_artist or ''} — {st.current_title or ''}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from mq_radio.web.app import run_server

    run_server(host=args.host, port=args.port, db_path=Path(args.db) if args.db else DB_PATH)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mq-radio", description="MQ Radio Automation M1 CLI")
    p.add_argument("--db", default=None, help="SQLite DB path (default: data/mq_radio.db)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init-db", help="Create/migrate SQLite schema")
    s.set_defaults(func=cmd_init_db)

    s = sub.add_parser("scan", help="Scan audio directory into library")
    s.add_argument("--path", default=None, help="Directory to scan")
    s.add_argument("--category", default="A")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("seed-demo", help="Seed categories, clock, rules, demo audio")
    s.set_defaults(func=cmd_seed_demo)

    s = sub.add_parser("generate-log", help="Generate 24h Living Log")
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.add_argument("--force", action="store_true", help="Overwrite MANUAL rows too")
    s.set_defaults(func=cmd_generate_log)

    s = sub.add_parser("show-log", help="Print Living Log")
    s.add_argument("--date", default=None)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_show_log)

    s = sub.add_parser("engine-step", help="Step MockEngine through committed log")
    s.add_argument("--date", default=None)
    s.add_argument("--action", choices=["step", "play", "stop", "skip"], default="step")
    s.set_defaults(func=cmd_engine_step)

    s = sub.add_parser("serve", help="Start On-Air web prototype")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

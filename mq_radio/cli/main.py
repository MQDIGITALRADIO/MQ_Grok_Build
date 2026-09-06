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
from mq_radio.living_log.service import list_events, load_sample_hour
from mq_radio.music_director.seed import seed_demo
from mq_radio.scheduler.clocks import OVERNIGHT_HOURS, describe_daypart_grid, list_clock_defs
from mq_radio.scheduler.generator import GenerateConstraints, generate_hour, generate_log
from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.placeholder_render import (
    render_placeholder_vt,
    render_placeholders_for_date,
    run_pd_assist_operator_path,
)
from mq_radio.voice_tracker.service import approve_ai_breaks, list_vt


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
    hours = None
    if getattr(args, "overnight", False):
        hours = sorted(OVERNIGHT_HOURS)
    elif getattr(args, "hours", None):
        hours = [int(h.strip()) for h in str(args.hours).split(",") if h.strip() != ""]
    elif getattr(args, "hour", None) is not None:
        hours = [int(args.hour)]
    constraints = None
    if getattr(args, "music_categories", None):
        constraints = GenerateConstraints(
            music_categories=tuple(
                c.strip() for c in str(args.music_categories).split(",") if c.strip()
            ),
            enforce_australian_min=bool(getattr(args, "enforce_au", False)),
            max_same_category_per_hour=getattr(args, "max_cat_per_hour", None),
            block_explicit=bool(getattr(args, "block_explicit", False)),
        )
    elif getattr(args, "enforce_au", False) or getattr(args, "max_cat_per_hour", None) or getattr(args, "block_explicit", False):
        constraints = GenerateConstraints(
            enforce_australian_min=bool(getattr(args, "enforce_au", False)),
            max_same_category_per_hour=getattr(args, "max_cat_per_hour", None),
            block_explicit=bool(getattr(args, "block_explicit", False)),
        )
    result = generate_log(
        log_date,
        db_path=Path(args.db) if args.db else None,
        force=args.force,
        hours=hours,
        constraints=constraints,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_show_clocks(args: argparse.Namespace) -> int:
    from mq_radio.db.connection import get_connection, init_db
    from mq_radio.scheduler.clocks import clocks_bundle

    db = Path(args.db) if getattr(args, "db", None) and args.db else None
    init_db(db)
    conn = get_connection(db)
    try:
        bundle = clocks_bundle(conn)
    except Exception:
        bundle = describe_daypart_grid()
    finally:
        conn.close()
    if args.json:
        print(json.dumps(bundle, indent=2, default=str))
        return 0
    print("MQ DIGITAL — category clocks / daypart grid")
    print("-" * 60)
    for clock in bundle.get("clocks") or list_clock_defs():
        slots = clock.get("slots") or []
        if "slot_count" in clock:
            sc, ms, vt = clock["slot_count"], clock.get("music_slots"), clock.get("vt_slots")
        else:
            sc = len(slots)
            ms = sum(1 for s in slots if s.get("event_type") == "MUSIC")
            vt = sum(1 for s in slots if s.get("event_type") == "VOICE_TRACK")
        print(
            f"{clock['code']:<12} {clock.get('name') or ''}  "
            f"slots={sc} music={ms} vt={vt}"
        )
    print()
    print("Hour → clock:")
    hour_clock = bundle.get("hour_clock") or {}
    line = []
    for h in range(24):
        code = hour_clock.get(str(h), "?")
        line.append(f"{h:02d}:{str(code)[:3]}")
        if len(line) == 6:
            print("  " + "  ".join(line))
            line = []
    if line:
        print("  " + "  ".join(line))
    print()
    print("AI never picks MUSIC live. VT placeholders → generate-ai-breaks → approve → Vocloner or render-placeholder-vt / pd-assist.")
    print("Clock Editor + Daypart Designer (On-Air CLOCKS) saves DB + data/clocks.json; ETM/HIT get fills.")
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



def cmd_load_sample_hour(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    log_date = args.date or date.today().isoformat()
    if str(log_date).lower() in ("today",):
        log_date = date.today().isoformat()
    result = load_sample_hour(
        log_date,
        db_path=Path(args.db) if args.db else None,
        hour=args.hour,
        clear_day=not args.no_clear,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    from mq_radio.web.app import run_server

    run_server(host=args.host, port=args.port, db_path=Path(args.db) if args.db else DB_PATH)
    return 0



def cmd_generate_ai_breaks(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    log_date = args.date or date.today().isoformat()
    result = generate_ai_breaks(
        log_date,
        db_path=Path(args.db) if args.db else None,
        station_name=args.station,
        style=args.style,
        insert_gaps=not args.no_insert,
        max_per_hour=args.max_per_hour,
        stride=args.stride,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) and "error" not in result else 1


def cmd_approve_ai_breaks(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    log_date = args.date or date.today().isoformat()
    result = approve_ai_breaks(log_date, db_path=Path(args.db) if args.db else None)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_list_vt(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    log_date = args.date  # optional
    rows = list_vt(
        log_date,
        db_path=Path(args.db) if args.db else None,
        status=args.status,
    )
    if not rows:
        print("No voice-track scripts" + (f" for {log_date}" if log_date else ""))
        return 0
    print(f"{'ID':>4}  {'DATE':<10}  {'POS':>4}  {'STATUS':<9}  {'VARIATION':<14}  SCRIPT")
    print("-" * 100)
    for r in rows:
        script = (r.get("script_text") or "").replace("\n", " ")
        if len(script) > 55:
            script = script[:52] + "..."
        print(
            f"{r['id']:4d}  {r.get('log_date',''):<10}  {r.get('position',0):4d}  "
            f"{r.get('status',''):<9}  {r.get('variation',''):<14}  {script}"
        )
    return 0



def cmd_render_placeholder(args: argparse.Namespace) -> int:
    init_db(Path(args.db) if args.db else None)
    db = Path(args.db) if args.db else None
    if args.event_id is not None:
        result = render_placeholder_vt(
            int(args.event_id), db_path=db, force=bool(args.force)
        )
    else:
        log_date = args.date or date.today().isoformat()
        result = render_placeholders_for_date(
            log_date, db_path=db, force=bool(args.force)
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_pd_assist(args: argparse.Namespace) -> int:
    """Overnight / PD assist: AI scripts → approve → placeholder attach (AI upstairs only)."""
    init_db(Path(args.db) if args.db else None)
    log_date = args.date or date.today().isoformat()
    result = run_pd_assist_operator_path(
        log_date,
        db_path=Path(args.db) if args.db else None,
        station_name=args.station,
        style=args.style,
        insert_gaps=not args.no_insert,
        approve=not args.no_approve,
        render_placeholders=not args.no_placeholder,
        force_placeholder=bool(args.force_placeholder),
        max_per_hour=args.max_per_hour,
        stride=args.stride,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mq-radio", description="MQ Radio Automation CLI (M2)")
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

    s = sub.add_parser("generate-log", help="Generate Living Log (24h or hour subset)")
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.add_argument("--force", action="store_true", help="Overwrite MANUAL rows too")
    s.add_argument("--hour", type=int, default=None, help="Generate a single hour 0-23")
    s.add_argument("--hours", default=None, help="Comma-separated hours, e.g. 23,0,1,2,3,4")
    s.add_argument("--overnight", action="store_true", help="Only overnight hours (23-04)")
    s.add_argument("--music-categories", default=None, help="Limit MUSIC cats, e.g. B,C")
    s.add_argument("--enforce-au", action="store_true", help="Hard-ish Australian min per hour")
    s.add_argument("--max-cat-per-hour", type=int, default=None, help="Cap same category / hour")
    s.add_argument("--block-explicit", action="store_true", help="Block explicit regardless of rules")
    s.set_defaults(func=cmd_generate_log)

    s = sub.add_parser("show-clocks", help="Show category clocks + daypart grid")
    s.add_argument("--json", action="store_true", help="JSON dump")
    s.set_defaults(func=cmd_show_clocks)

    s = sub.add_parser("show-log", help="Print Living Log")
    s.add_argument("--date", default=None)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_show_log)

    s = sub.add_parser("engine-step", help="Step MockEngine through committed log")
    s.add_argument("--date", default=None)
    s.add_argument("--action", choices=["step", "play", "stop", "skip"], default="step")
    s.set_defaults(func=cmd_engine_step)


    s = sub.add_parser("generate-ai-breaks", help="Generate AI VT scripts into Living Log gaps/placeholders")
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.add_argument("--station", default="MQ Digital")
    s.add_argument("--style", default="warm")
    s.add_argument("--no-insert", action="store_true", help="Only fill existing VT placeholders")
    s.add_argument("--max-per-hour", type=int, default=2)
    s.add_argument("--stride", type=int, default=2, help="Insert on every Nth music→music gap")
    s.set_defaults(func=cmd_generate_ai_breaks)

    s = sub.add_parser("approve-ai-breaks", help="Approve DRAFT AI voice-track scripts")
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.set_defaults(func=cmd_approve_ai_breaks)

    s = sub.add_parser("list-vt", help="List voice-track scripts")
    s.add_argument("--date", default=None)
    s.add_argument("--status", default=None, help="DRAFT|APPROVED")
    s.set_defaults(func=cmd_list_vt)


    s = sub.add_parser("load-sample-hour", help="Load editable 1-hour sample Living Log block")
    s.add_argument("--date", default="today", help="YYYY-MM-DD or today")
    s.add_argument("--hour", type=int, default=12, help="Hour start 0-23 (default 12)")
    s.add_argument("--no-clear", action="store_true", help="Do not clear existing day events")
    s.set_defaults(func=cmd_load_sample_hour)

    s = sub.add_parser(
        "render-placeholder-vt",
        help="Attach PCM placeholder WAV to approved VT(s) on Living Log (not Vocloner voice)",
    )
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.add_argument("--event-id", type=int, default=None, help="Single log_event id")
    s.add_argument("--force", action="store_true", help="Replace existing placeholder audio")
    s.set_defaults(func=cmd_render_placeholder)

    s = sub.add_parser(
        "pd-assist",
        help="PD assist overnight path: generate AI breaks → approve → placeholder attach (AI upstairs only)",
    )
    s.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    s.add_argument("--station", default="MQ Digital")
    s.add_argument("--style", default="warm")
    s.add_argument("--no-insert", action="store_true")
    s.add_argument("--no-approve", action="store_true")
    s.add_argument("--no-placeholder", action="store_true")
    s.add_argument("--force-placeholder", action="store_true")
    s.add_argument("--max-per-hour", type=int, default=2)
    s.add_argument("--stride", type=int, default=2)
    s.set_defaults(func=cmd_pd_assist)

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

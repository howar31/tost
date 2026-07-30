#!/usr/bin/env python3
"""TOST CLI — self-auditable Tesla order tracker. Python stdlib only."""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tost", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="interactive Tesla login (tokens -> Keychain)")

    p_fetch = sub.add_parser("fetch", help="snapshot + diff + persist")
    p_fetch.add_argument("--notify", action="store_true", help="macOS notification on changes")
    p_fetch.add_argument("--quiet", action="store_true", help="no output when nothing changed")
    p_fetch.add_argument("--json", action="store_true", help="print events as JSON")

    p_status = sub.add_parser("status", help="current order summary (fetches fresh)")
    p_status.add_argument("--cached", action="store_true", help="use local data, no network")
    p_status.add_argument("--json", action="store_true")

    p_timeline = sub.add_parser("timeline", help="change history")
    p_timeline.add_argument("-n", type=int, default=None, help="last N events")
    p_timeline.add_argument("--json", action="store_true")

    p_raw = sub.add_parser("raw", help="dump latest snapshot JSON")
    p_raw.add_argument("--order", help="filter by reference number")

    sub.add_parser("export", help="summary + events + poll log as one JSON doc")

    p_agent = sub.add_parser("agent", help="manage periodic launchd agent")
    p_agent.add_argument("action", choices=["install", "uninstall", "status"])
    p_agent.add_argument("--interval", type=int, default=60, metavar="MINUTES",
                         help="fetch interval in minutes (install only, default 60)")

    args = parser.parse_args(argv)
    store = Store(BASE_DIR / "data")

    if args.command == "auth":
        from app import auth
        try:
            auth.interactive_login()
            return 0
        except auth.AuthRequired as e:
            print(f"auth failed: {e}", file=sys.stderr)
            return 3
        except KeyboardInterrupt:
            print("\nauth cancelled", file=sys.stderr)
            return 1
    if args.command == "fetch":
        from app.cli import cmd_fetch
        return cmd_fetch(args, store)
    if args.command == "status":
        # status implies a fetch first; reuse fetch flags with safe defaults
        args.notify = False
        args.quiet = True
        from app.cli import cmd_status
        return cmd_status(args, store)
    if args.command == "timeline":
        from app.cli import cmd_timeline
        return cmd_timeline(args, store)
    if args.command == "raw":
        from app.cli import cmd_raw
        return cmd_raw(args, store)
    if args.command == "export":
        from app.cli import cmd_export
        return cmd_export(args, store)
    if args.command == "agent":
        from app import agent
        if args.action == "install":
            agent.install(BASE_DIR / "tost.py", BASE_DIR / "data" / "logs" / "agent.log",
                          interval_minutes=args.interval)
            return 0
        if args.action == "uninstall":
            agent.uninstall()
            return 0
        return agent.status()
    return 1


if __name__ == "__main__":
    sys.exit(main())

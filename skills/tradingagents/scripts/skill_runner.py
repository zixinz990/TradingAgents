"""Command-line wrapper for deterministic TradingAgents skill runtime helpers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-run", help="Create a skill run state directory")
    init_parser.add_argument("config", type=Path)

    next_parser = subparsers.add_parser("next-step", help="Emit the next role packet")
    next_parser.add_argument("report_dir", type=Path)

    tool_parser = subparsers.add_parser("run-tool-request", help="Execute a validated role tool request")
    tool_parser.add_argument("report_dir", type=Path)
    tool_parser.add_argument("--request", type=Path)

    apply_parser = subparsers.add_parser("apply-step", help="Apply the current role report into state")
    apply_parser.add_argument("report_dir", type=Path)
    apply_parser.add_argument("--role-id")

    finalize_parser = subparsers.add_parser("finalize-run", help="Assemble final artifacts")
    finalize_parser.add_argument("report_dir", type=Path)

    parity_parser = subparsers.add_parser("parity-check", help="Compare API and skill state logs")
    parity_parser.add_argument("api_state", type=Path)
    parity_parser.add_argument("skill_state", type=Path)

    args = parser.parse_args(argv)

    try:
        if args.command == "init-run":
            print(runtime.init_run(args.config))
        elif args.command == "next-step":
            print(runtime.next_step(args.report_dir))
        elif args.command == "run-tool-request":
            print(runtime.run_tool_request(args.report_dir, request_path=args.request))
        elif args.command == "apply-step":
            print(runtime.apply_step(args.report_dir, role_id=args.role_id))
        elif args.command == "finalize-run":
            print(json.dumps(runtime.finalize_run(args.report_dir), indent=2))
        elif args.command == "parity-check":
            print(json.dumps(runtime.parity_check(args.api_state, args.skill_state), indent=2))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

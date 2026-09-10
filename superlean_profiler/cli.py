"""``slprof`` — profile MCP and skill token cost across agent trajectories."""

from __future__ import annotations

import argparse
import sys

from . import _render
from ._advice import findings
from ._metrics import aggregate
from ._profile import profile, select_records


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="slprof",
        description="Profile which MCP servers and skills eat your tokens.",
    )
    p.add_argument(
        "view",
        nargs="?",
        default="all",
        choices=["all", "mcp", "skills", "advice"],
        help="what to report (default: all)",
    )
    p.add_argument("--local", action="store_true", help="only trajectories of this directory")
    p.add_argument("--agent", action="append", default=[], help="restrict to an agent (repeatable)")
    p.add_argument("--since", default="", help="ISO date lower bound, e.g. 2026-06-01")
    p.add_argument("--limit", type=int, default=0, help="profile at most N most recent sessions")
    p.add_argument("--top", type=int, default=15, help="rows per table (default: 15)")
    p.add_argument("--jobs", type=int, default=0, help="parallel workers (default: CPU count)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    records = select_records(
        local=args.local,
        agents=tuple(args.agent),
        since=args.since,
        limit=args.limit,
    )
    if not records:
        return 0

    report = aggregate(profile(records, jobs=args.jobs))
    found = findings(report)

    if args.json:
        print(_render.as_json(report, found))
        return 0

    blocks: list[str] = []
    if args.view != "advice":
        blocks.append(_render.header(report))
    if args.view in ("all", "mcp"):
        blocks += [
            _render.servers_table(report, args.top),
            _render.mcp_tools_table(report, args.top),
        ]
    if args.view in ("all", "skills"):
        blocks.append(_render.skills_table(report, args.top))
    if args.view in ("all", "advice"):
        blocks.append(_render.findings_table(found, args.top))

    out = "\n\n".join(b for b in blocks if b)
    if out:
        print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

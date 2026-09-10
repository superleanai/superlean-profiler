"""Console tables and JSON output."""

from __future__ import annotations

import json
from dataclasses import asdict

from ._advice import Finding
from ._metrics import EntityStat, Report


def tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def table(headers: list[str], rows: list[list[str]], indent: str = "") -> str:
    if not rows:
        return ""
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    right = {i for i in range(len(headers)) if all(_numeric(r[i]) for r in rows)}

    def fmt(cells: list[str]) -> str:
        parts = [
            cells[i].rjust(widths[i]) if i in right else cells[i].ljust(widths[i])
            for i in range(len(cells))
        ]
        return indent + "  ".join(parts).rstrip()

    sep = indent + "  ".join("-" * w for w in widths)
    return "\n".join([fmt(headers), sep, *(fmt(r) for r in rows)])


def _numeric(cell: str) -> bool:
    return bool(cell) and cell[0].isdigit() or cell in {"-", "0"}


def header(report: Report) -> str:
    agents = ", ".join(f"{a} {n}" for a, n in sorted(report.agents.items(), key=lambda kv: -kv[1]))
    return (
        f"{report.sessions} sessions, {report.requests} requests, "
        f"{tok(report.total_tokens)} tokens  [{agents}]\n"
        f"resident context measured in {report.sessions_with_resident_data} session(s)"
    )


def servers_table(report: Report, limit: int = 15) -> str:
    rows = []
    for stat in report.ranked(report.servers)[:limit]:
        rows.append(
            [
                stat.key,
                str(stat.calls),
                f"{stat.sessions_used}/{stat.sessions_present}",
                tok(stat.resident_median),
                tok(stat.resident_tokens),
                tok(stat.active_tokens),
                tok(stat.total_tokens),
            ]
        )
    return table(
        ["MCP SERVER", "CALLS", "USED/SEEN", "RES/REQ", "RESIDENT", "ACTIVE", "TOTAL"], rows
    )


def mcp_tools_table(report: Report, limit: int = 15) -> str:
    rows = []
    used = [s for s in report.mcp_tools.values() if s.calls]
    for stat in sorted(used, key=lambda s: -s.active_tokens)[:limit]:
        rows.append(
            [
                stat.key,
                str(stat.calls),
                str(stat.errors),
                tok(stat.tokens_per_use),
                tok(stat.p95_result),
                tok(stat.active_tokens),
            ]
        )
    return table(["MCP TOOL", "CALLS", "ERR", "TOK/USE", "P95 RESULT", "ACTIVE"], rows)


def skills_table(report: Report, limit: int = 20) -> str:
    rows = []
    for stat in report.ranked(report.skills)[:limit]:
        rows.append(
            [
                stat.key,
                str(stat.calls),
                f"{stat.sessions_used}/{stat.sessions_present}",
                tok(stat.resident_median),
                tok(stat.resident_tokens),
                tok(stat.body_tokens),
                tok(stat.total_tokens),
            ]
        )
    return table(
        ["SKILL", "USES", "USED/SEEN", "RES/REQ", "RESIDENT", "BODY", "TOTAL"],
        rows,
    )


def findings_table(items: list[Finding], limit: int = 20) -> str:
    rows = [
        [f.severity, f.entity, f.action, tok(f.tokens_saved), f.rationale] for f in items[:limit]
    ]
    return table(["SEV", "ENTITY", "ACTION", "SAVES", "WHY"], rows)


def as_json(report: Report, items: list[Finding]) -> str:
    def dump(bucket: dict[str, EntityStat]) -> list[dict]:
        out = []
        for stat in report.ranked(bucket):
            data = asdict(stat)
            data.pop("result_sizes", None)
            data.pop("resident_per_request", None)
            data.update(
                active_tokens=stat.active_tokens,
                total_tokens=stat.total_tokens,
                resident_per_request_median=stat.resident_median,
                use_rate=round(stat.use_rate, 4),
                tokens_per_use=stat.tokens_per_use,
                p95_result_tokens=stat.p95_result,
                error_rate=round(stat.error_rate, 4),
            )
            out.append(data)
        return out

    return json.dumps(
        {
            "sessions": report.sessions,
            "requests": report.requests,
            "agents": report.agents,
            "prompt_tokens": report.prompt_tokens,
            "completion_tokens": report.completion_tokens,
            "sessions_with_resident_data": report.sessions_with_resident_data,
            "skill_listing_tokens": report.skill_listing_tokens,
            "agent_listing_tokens": report.agent_listing_tokens,
            "broken_servers": report.broken_servers,
            "mcp_servers": dump(report.servers),
            "mcp_tools": dump(report.mcp_tools),
            "skills": dump(report.skills),
            "findings": [asdict(f) for f in items],
        },
        indent=2,
    )

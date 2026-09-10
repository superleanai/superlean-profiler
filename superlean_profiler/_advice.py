"""Turn measurements into ranked, actionable findings."""

from __future__ import annotations

from dataclasses import dataclass

from ._metrics import EntityStat, Report


@dataclass(frozen=True)
class Finding:
    severity: str  # high | medium | low
    entity: str
    action: str
    tokens_saved: int
    rationale: str


def _sev(tokens: int) -> str:
    if tokens > 500_000:
        return "high"
    return "medium" if tokens > 50_000 else "low"


def findings(report: Report) -> list[Finding]:
    out: list[Finding] = []

    for stat in report.waste():
        what = "MCP server" if stat.kind == "mcp-server" else "skill"
        out.append(
            Finding(
                _sev(stat.resident_tokens),
                stat.key,
                "remove",
                stat.resident_tokens,
                f"{what} resident in {stat.sessions_present} session(s) "
                f"({stat.resident_median} tok/request), never called once",
            )
        )

    for server, sessions in report.broken_servers.items():
        broken = report.servers.get(server)
        out.append(
            Finding(
                "medium",
                server,
                "remove",
                broken.resident_tokens if broken else 0,
                f"server failed in {sessions} session(s): it costs context and delivers nothing",
            )
        )

    def _low_use(bucket: dict[str, EntityStat], label: str) -> None:
        for stat in bucket.values():
            if 0 < stat.use_rate < 0.05 and stat.resident_tokens > 20_000:
                out.append(
                    Finding(
                        _sev(stat.resident_tokens),
                        stat.key,
                        "defer",
                        int(stat.resident_tokens * (1 - stat.use_rate)),
                        f"{label} used in {stat.sessions_used}/{stat.sessions_present} "
                        f"sessions ({stat.use_rate:.1%}) yet resident in all of them",
                    )
                )

    _low_use(report.servers, "MCP server")
    _low_use(report.skills, "skill")

    for stat in report.mcp_tools.values():
        if stat.p95_result > 5_000:
            out.append(
                Finding(
                    _sev(stat.result_tokens),
                    stat.key,
                    "trim-results",
                    stat.result_tokens // 2,
                    f"p95 result is {stat.p95_result} tok over {stat.calls} call(s): "
                    "paginate or select fields",
                )
            )
        if stat.calls >= 5 and stat.error_rate > 0.3:
            out.append(
                Finding(
                    "medium",
                    stat.key,
                    "fix-or-drop",
                    stat.active_tokens // 2,
                    f"{stat.error_rate:.0%} of {stat.calls} calls errored; retries pay twice",
                )
            )

    for stat in report.skills.values():
        if stat.calls and stat.body_tokens // stat.calls > 3_000:
            out.append(
                Finding(
                    _sev(stat.body_tokens),
                    stat.key,
                    "split-skill",
                    stat.body_tokens // 2,
                    f"body is {stat.body_tokens // stat.calls} tok per invocation: "
                    "move detail behind progressive disclosure",
                )
            )

    return sorted(out, key=lambda f: -f.tokens_saved)

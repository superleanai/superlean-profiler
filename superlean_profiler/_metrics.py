"""Aggregate per-session facts into per-entity statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from ._collect import split_mcp_name
from ._profile import SessionFacts


@dataclass
class EntityStat:
    """Cost of one MCP server, MCP tool or skill across all profiled sessions."""

    kind: str  # "mcp-server" | "mcp-tool" | "skill" | "tool"
    key: str
    sessions_present: int = 0
    sessions_used: int = 0
    calls: int = 0
    errors: int = 0
    arg_tokens: int = 0
    result_tokens: int = 0
    body_tokens: int = 0
    #: tokens the entity adds to *every request* of a session it is present in
    resident_per_request: list[int] = field(default_factory=list)
    #: resident_per_request x that session's request count, summed
    resident_tokens: int = 0
    result_sizes: list[int] = field(default_factory=list)

    @property
    def active_tokens(self) -> int:
        return self.arg_tokens + self.result_tokens + self.body_tokens

    @property
    def total_tokens(self) -> int:
        return self.active_tokens + self.resident_tokens

    @property
    def use_rate(self) -> float:
        return self.sessions_used / self.sessions_present if self.sessions_present else 0.0

    @property
    def tokens_per_use(self) -> int:
        return self.active_tokens // self.calls if self.calls else 0

    @property
    def resident_median(self) -> int:
        return int(median(self.resident_per_request)) if self.resident_per_request else 0

    @property
    def p95_result(self) -> int:
        if not self.result_sizes:
            return 0
        ordered = sorted(self.result_sizes)
        return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0


@dataclass
class Report:
    sessions: int = 0
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    agents: dict[str, int] = field(default_factory=dict)
    servers: dict[str, EntityStat] = field(default_factory=dict)
    mcp_tools: dict[str, EntityStat] = field(default_factory=dict)
    skills: dict[str, EntityStat] = field(default_factory=dict)
    builtins: dict[str, EntityStat] = field(default_factory=dict)
    skill_listing_per_request: list[int] = field(default_factory=list)
    skill_listing_tokens: int = 0
    agent_listing_tokens: int = 0
    broken_servers: dict[str, int] = field(default_factory=dict)
    sessions_with_resident_data: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def ranked(self, entities: dict[str, EntityStat]) -> list[EntityStat]:
        return sorted(entities.values(), key=lambda s: -s.total_tokens)

    def waste(self) -> list[EntityStat]:
        """Entities that are resident in some session but never used anywhere."""
        out = [s for s in self.servers.values() if s.calls == 0 and s.resident_tokens > 0]
        out += [s for s in self.skills.values() if s.calls == 0 and s.resident_tokens > 0]
        return sorted(out, key=lambda s: -s.resident_tokens)


def _stat(bucket: dict[str, EntityStat], kind: str, key: str) -> EntityStat:
    if key not in bucket:
        bucket[key] = EntityStat(kind=kind, key=key)
    return bucket[key]


def aggregate(all_facts: list[SessionFacts]) -> Report:
    report = Report()

    for facts in all_facts:
        usage = facts.usage
        report.sessions += 1
        report.requests += usage.requests
        report.prompt_tokens += usage.prompt_tokens
        report.completion_tokens += usage.completion_tokens
        report.agents[usage.agent] = report.agents.get(usage.agent, 0) + 1
        requests = max(usage.requests, 1)

        # --- resident side (Claude Code only) ---
        used_servers = {e.server for e in facts.events if e.kind == "mcp"}
        used_skills = {e.name for e in facts.events if e.kind == "skill"}
        if facts.resident is not None:
            res = facts.resident
            report.sessions_with_resident_data += 1
            for server, tokens in res.server_resident_tokens().items():
                stat = _stat(report.servers, "mcp-server", server)
                stat.sessions_present += 1
                stat.resident_per_request.append(tokens)
                stat.resident_tokens += tokens * requests
                if server in used_servers:
                    stat.sessions_used += 1
            for name, tokens in res.tool_listing_tokens.items():
                if (parts := split_mcp_name(name)) is None:
                    continue
                stat = _stat(report.mcp_tools, "mcp-tool", f"{parts[0]}/{parts[1]}")
                stat.sessions_present += 1
                stat.resident_per_request.append(tokens)
                stat.resident_tokens += tokens * requests
            # each skill is charged its own lines of the listing: a verbose
            # description costs more than a terse one, on every request
            shares = res.skill_listing_by_name
            fallback = res.skill_listing_tokens // len(res.skill_names) if res.skill_names else 0
            for name in res.skill_names | set(shares):
                share = shares.get(name, fallback)
                stat = _stat(report.skills, "skill", name)
                stat.sessions_present += 1
                stat.resident_per_request.append(share)
                stat.resident_tokens += share * requests
                if name in used_skills:
                    stat.sessions_used += 1
            report.skill_listing_per_request.append(res.skill_listing_tokens)
            report.skill_listing_tokens += res.skill_listing_tokens * requests
            report.agent_listing_tokens += res.agent_listing_tokens * requests
            # only *failed* counts as broken: "pending" is a transient
            # startup state that resolves in the same session
            for server in res.failed_mcp_servers:
                report.broken_servers[server] = report.broken_servers.get(server, 0) + 1

        # --- active side (every agent) ---
        for event in facts.events:
            if event.kind == "mcp" and event.server:
                for stat in (
                    _stat(report.servers, "mcp-server", event.server),
                    _stat(report.mcp_tools, "mcp-tool", f"{event.server}/{event.name}"),
                ):
                    stat.calls += 1
                    stat.arg_tokens += event.arg_tokens
                    stat.result_tokens += event.result_tokens
                    stat.errors += int(event.is_error)
                    stat.result_sizes.append(event.result_tokens)
            elif event.kind == "skill":
                stat = _stat(report.skills, "skill", event.name)
                stat.calls += 1
                stat.arg_tokens += event.arg_tokens
                stat.body_tokens += event.body_tokens
            else:
                stat = _stat(report.builtins, "tool", event.name)
                stat.calls += 1
                stat.arg_tokens += event.arg_tokens
                stat.result_tokens += event.result_tokens
                stat.errors += int(event.is_error)
                stat.result_sizes.append(event.result_tokens)

    # a session that used an entity is by definition a session it was present in
    for bucket in (report.servers, report.mcp_tools, report.skills):
        for stat in bucket.values():
            stat.sessions_used = max(stat.sessions_used, 1 if stat.calls else 0)
            stat.sessions_present = max(stat.sessions_present, stat.sessions_used)

    return report

"""Agent-agnostic collection of MCP and skill events from trajectories.

Built exclusively on the public ``trajectoriz`` API (``iter_records`` /
``parse_record`` / ``estimate_tokens``), so every agent format trajectoriz
supports is covered. Claude Code-specific extras (exact result sizes,
``is_error``, resident context) live in :mod:`superlean_profiler._claude_raw`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

import trajectoriz as t

Kind = Literal["mcp", "skill", "toolsearch", "builtin"]

#: trajectoriz truncates tool results at 4000 chars and appends this marker.
#: We recover the real size from it — fat results are exactly what we profile.
_TRUNC_RE = re.compile(r"\n… \[(\d+) chars truncated\]$")

#: A Claude Code skill body is injected as the user turn right after the
#: ``Skill`` call, prefixed with this line.
_SKILL_BODY_PREFIX = "Base directory for this skill:"

_ERROR_RE = re.compile(
    r"^(error|Error:|InputValidationError|<tool_use_error>)|tool_use_error|is_error",
)


@dataclass(frozen=True)
class ToolEvent:
    """One tool call (MCP, skill, ToolSearch or built-in) with its token cost."""

    session_id: str
    agent: str
    timestamp: str
    step_id: str
    kind: Kind
    server: str | None
    name: str
    arg_tokens: int = 0
    result_tokens: int = 0
    result_chars: int = 0
    result_truncated: bool = False
    body_tokens: int = 0  # skills only: the injected SKILL.md body
    is_error: bool = False

    @property
    def entity(self) -> str:
        """Reporting key: the server for MCP tools, the skill name for skills."""
        if self.kind == "mcp":
            return f"mcp:{self.server}"
        if self.kind == "skill":
            return f"skill:{self.name}"
        return f"tool:{self.name}"

    @property
    def total_tokens(self) -> int:
        return self.arg_tokens + self.result_tokens + self.body_tokens


@dataclass(frozen=True)
class SessionUsage:
    """Per-session totals, so entity cost can be expressed as a share."""

    session_id: str
    agent: str
    timestamp: str
    cwd: str
    model_name: str | None
    steps: int
    requests: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    tool_calls: int
    compaction_count: int


def split_mcp_name(name: str) -> tuple[str, str] | None:
    """``mcp__server__tool`` -> ``(server, tool)``, else ``None``.

    Tool names may contain ``__`` themselves, so only the first two segments
    are structural.
    """
    if not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__") :]
    server, sep, tool = rest.partition("__")
    if not sep or not server:
        return None
    return server, tool


def _result_size(content: object) -> tuple[int, int, bool]:
    """(tokens, chars, truncated) for a tool result, undoing truncation."""
    text = content if isinstance(content, str) else str(content or "")
    m = _TRUNC_RE.search(text)
    if not m:
        return t.estimate_tokens(text), len(text), False
    kept = text[: m.start()]
    real_chars = len(kept) + int(m.group(1))
    # scale the estimate to the real size rather than under-reporting it
    return max(1, -(-real_chars // 4)), real_chars, True


def _is_error(content: object) -> bool:
    text = content if isinstance(content, str) else str(content or "")
    return bool(_ERROR_RE.search(text[:200]))


def iter_tool_calls(traj: t.ParsedTrajectory) -> Iterator[tuple[dict, dict, str | None]]:
    """Yield ``(step, tool_call, result_content)`` already joined on call id.

    trajectoriz stores results in a *later* step's ``observation``, so every
    consumer has to build this index. Proposed upstream as
    ``trajectoriz.iter_tool_calls``.
    """
    results: dict[str, str] = {}
    for step in traj.steps:
        for res in (step.get("observation") or {}).get("results", []):
            cid = res.get("source_call_id")
            if cid:
                results[cid] = res.get("content", "")
    for step in traj.steps:
        for call in step.get("tool_calls", []) or []:
            yield step, call, results.get(call.get("tool_call_id", ""))


def _skill_bodies(traj: t.ParsedTrajectory) -> list[int]:
    """Token counts of injected skill bodies, in invocation order."""
    return [
        t.estimate_tokens(msg)
        for step in traj.steps
        if step.get("source") == "user"
        and (msg := str(step.get("message") or "")).startswith(_SKILL_BODY_PREFIX)
    ]


def iter_events(record: t.TrajectoryRecord, traj: t.ParsedTrajectory) -> Iterator[ToolEvent]:
    """Yield one :class:`ToolEvent` per tool call in a parsed trajectory."""
    session_id = traj.session_id or record.id
    bodies = _skill_bodies(traj)
    skill_seen = 0

    for step, call, result in iter_tool_calls(traj):
        name = str(call.get("function_name") or "")
        if not name:
            continue
        r_tokens, r_chars, truncated = _result_size(result)
        kind: Kind = "builtin"
        server: str | None = None
        body = 0

        if (parts := split_mcp_name(name)) is not None:
            kind, (server, name) = "mcp", parts
        elif name == "Skill":
            kind = "skill"
            name = str((call.get("arguments") or {}).get("skill") or "?")
            # bodies arrive in call order; pair positionally
            if skill_seen < len(bodies):
                body = bodies[skill_seen]
            skill_seen += 1
        elif name == "ToolSearch":
            kind = "toolsearch"

        yield ToolEvent(
            session_id=session_id,
            agent=record.agent,
            timestamp=str(step.get("timestamp") or record.timestamp),
            step_id=str(step.get("step_id") or ""),
            kind=kind,
            server=server,
            name=name,
            arg_tokens=t.estimate_tokens(call.get("arguments")),
            result_tokens=r_tokens,
            result_chars=r_chars,
            result_truncated=truncated,
            body_tokens=body,
            is_error=_is_error(result),
        )


def session_usage(record: t.TrajectoryRecord, traj: t.ParsedTrajectory) -> SessionUsage:
    requests = sum(1 for s in traj.steps if s.get("metrics"))
    return SessionUsage(
        session_id=traj.session_id or record.id,
        agent=record.agent,
        timestamp=record.timestamp,
        cwd=traj.cwd,
        model_name=traj.model_name,
        steps=len(traj.steps),
        requests=requests,
        prompt_tokens=traj.total_prompt_tokens,
        completion_tokens=traj.total_completion_tokens,
        cached_tokens=traj.total_cached_tokens,
        tool_calls=traj.total_tool_calls,
        compaction_count=traj.compaction_count,
    )


def collect(
    records: Iterable[t.TrajectoryRecord],
    cache_dir: str | None = None,
) -> tuple[list[SessionUsage], list[ToolEvent]]:
    """Parse records and return per-session usage plus every tool event."""
    sessions: list[SessionUsage] = []
    events: list[ToolEvent] = []
    for record in records:
        traj = t.parse_record(record, cache_dir=cache_dir)
        if traj is None:
            continue
        sessions.append(session_usage(record, traj))
        events.extend(iter_events(record, traj))
    return sessions, events

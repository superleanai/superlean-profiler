"""Claude Code raw-JSONL reader for *resident* context cost.

The expensive part of an MCP server or a skill is not its calls, it is the text
it keeps in every request: tool schemas, server instruction blocks, the skill
listing. Claude Code records all of it in ``attachment`` entries that
trajectoriz does not surface in ``ParsedTrajectory.steps``:

===========================  =====================================================
attachment type              what it gives us
===========================  =====================================================
``deferred_tools_record``    ``entries[].description`` + ``input_schema`` — the
                             exact per-tool schema, i.e. real resident tokens
``deferred_tools_delta``     names/lines of deferred tools, plus
                             ``pendingMcpServers`` / ``failedMcpServers``
``mcp_instructions_delta``   per-server instruction block (``addedNames`` is
                             index-aligned with ``addedBlocks``)
``skill_listing``            the whole skill listing text + ``names``
``agent_listing_delta``      subagent listing lines
``prompt_snapshot``          the full system prompt (baseline cost)
===========================  =====================================================

Raw reading also recovers what the public API loses: untruncated tool-result
sizes and the ``is_error`` flag.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import trajectoriz as t

from ._collect import split_mcp_name

RESIDENT_ATTACHMENTS = (
    "deferred_tools_record",
    "deferred_tools_delta",
    "mcp_instructions_delta",
    "skill_listing",
    "agent_listing_delta",
    "prompt_snapshot",
)


def canonical_server(name: object) -> str:
    """Normalize an MCP server name to the slug used in ``mcp__<server>__<tool>``.

    ``mcp_instructions_delta`` reports display names ("claude.ai gh") while tool
    names carry slugs ("claude_ai_gh"); without this the same server is counted
    twice. ``failedMcpServers`` entries are objects
    (``{name, errorCode, error}``), not strings, so both shapes are accepted.
    """
    if isinstance(name, dict):
        name = name.get("name") or ""
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(name).strip())


_SKILL_LINE_RE = re.compile(r"^- ([A-Za-z0-9][\w.:-]*):")


def split_skill_listing(content: str) -> dict[str, int]:
    """``- name: description`` listing -> per-skill token cost.

    Descriptions run over several lines, so continuation lines are charged to
    the skill above them. A verbose description is paid on every request, so
    this is what makes one skill more expensive than another.
    """
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        if (m := _SKILL_LINE_RE.match(line)) is not None:
            current = m.group(1)
            out.setdefault(current, [])
        if current is not None:
            out[current].append(line)
    return {name: t.estimate_tokens("\n".join(lines)) for name, lines in out.items()}


@dataclass
class ResidentFacts:
    """Measured resident context of one Claude Code session."""

    session_id: str = ""
    system_prompt_tokens: int = 0
    #: tool name -> full description+schema tokens (exact, from
    #: ``deferred_tools_record``); paid only once the tool is actually loaded
    tool_schema_tokens: dict[str, int] = field(default_factory=dict)
    #: tool name -> one-line listing tokens; paid on *every* request while the
    #: tool is merely announced as deferred
    tool_listing_tokens: dict[str, int] = field(default_factory=dict)
    #: MCP server -> instruction-block tokens
    mcp_instruction_tokens: dict[str, int] = field(default_factory=dict)
    #: tool names announced as available (deferred listing)
    deferred_tool_names: set[str] = field(default_factory=set)
    #: MCP servers that never came up / failed — pure waste
    pending_mcp_servers: set[str] = field(default_factory=set)
    failed_mcp_servers: set[str] = field(default_factory=set)
    #: whole skill listing, and each skill's own share of it
    skill_listing_tokens: int = 0
    skill_listing_by_name: dict[str, int] = field(default_factory=dict)
    skill_names: set[str] = field(default_factory=set)
    agent_listing_tokens: int = 0

    @property
    def mcp_servers(self) -> set[str]:
        servers = set(self.mcp_instruction_tokens)
        for name in self.deferred_tool_names:
            if (parts := split_mcp_name(name)) is not None:
                servers.add(parts[0])
        return servers

    def server_resident_tokens(self) -> dict[str, int]:
        """Per-server cost paid on *every* request: instructions + tool listing.

        This is the number that matters for "should I remove this server?".
        """
        out: Counter[str] = Counter()
        for server, tokens in self.mcp_instruction_tokens.items():
            out[server] += tokens
        for name, tokens in self.tool_listing_tokens.items():
            if (parts := split_mcp_name(name)) is not None:
                out[parts[0]] += tokens
        for server in self.mcp_servers:
            out.setdefault(server, 0)
        return dict(out)

    def server_schema_tokens(self) -> dict[str, int]:
        """Per-server cost of full tool schemas, paid once a tool is loaded.

        Compared against :meth:`server_resident_tokens` it quantifies what tool
        deferral is saving (or would save).
        """
        out: Counter[str] = Counter()
        for name, tokens in self.tool_schema_tokens.items():
            if (parts := split_mcp_name(name)) is not None:
                out[parts[0]] += tokens
        return dict(out)


def _iter_attachments(path: Path):
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            if '"attachment"' not in raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            att = entry.get("attachment")
            if isinstance(att, dict) and att.get("type"):
                yield entry, att


def resident_facts(jsonl_path: str | Path) -> ResidentFacts:
    """Measure the resident context of a Claude Code trajectory file."""
    path = Path(jsonl_path)
    facts = ResidentFacts()

    for entry, att in _iter_attachments(path):
        if not facts.session_id:
            facts.session_id = entry.get("sessionId") or entry.get("session_id") or ""
        kind = att["type"]

        if kind == "prompt_snapshot":
            facts.system_prompt_tokens += t.estimate_tokens(att.get("systemPrompt"))

        elif kind == "deferred_tools_record":
            for tool in att.get("entries") or []:
                name = tool.get("name")
                if not name:
                    continue
                facts.tool_schema_tokens[name] = t.estimate_tokens(tool.get("description")) + (
                    t.estimate_tokens(tool.get("input_schema"))
                )

        elif kind == "deferred_tools_delta":
            names = att.get("addedNames") or []
            lines = att.get("addedLines") or []
            facts.deferred_tool_names.update(names)
            facts.deferred_tool_names.difference_update(att.get("removedNames") or [])
            for name, line in zip(names, lines, strict=False):
                facts.tool_listing_tokens[name] = t.estimate_tokens(line)
            facts.pending_mcp_servers.update(
                canonical_server(s) for s in att.get("pendingMcpServers") or []
            )
            facts.failed_mcp_servers.update(
                canonical_server(s) for s in att.get("failedMcpServers") or []
            )

        elif kind == "mcp_instructions_delta":
            for name, block in zip(
                att.get("addedNames") or [], att.get("addedBlocks") or [], strict=False
            ):
                facts.mcp_instruction_tokens[canonical_server(name)] = t.estimate_tokens(block)
            for name in att.get("removedNames") or []:
                facts.mcp_instruction_tokens.pop(canonical_server(name), None)

        elif kind == "skill_listing":
            facts.skill_listing_tokens += t.estimate_tokens(att.get("content"))
            facts.skill_names.update(att.get("names") or [])
            for name, tokens in split_skill_listing(att.get("content") or "").items():
                facts.skill_listing_by_name[name] = tokens

        elif kind == "agent_listing_delta":
            facts.agent_listing_tokens += t.estimate_tokens(att.get("addedLines"))

    return facts


def exact_result_sizes(jsonl_path: str | Path) -> dict[str, tuple[int, bool]]:
    """``tool_use_id -> (result tokens, is_error)`` read untruncated from the raw file."""
    out: dict[str, tuple[int, bool]] = {}
    with Path(jsonl_path).open(encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            if '"tool_result"' not in raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "tool_result":
                    continue
                tid = part.get("tool_use_id")
                if tid:
                    out[tid] = (
                        t.estimate_tokens(part.get("content")),
                        bool(part.get("is_error")),
                    )
    return out

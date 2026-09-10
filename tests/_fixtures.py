"""Synthetic Claude Code trajectories exercising MCP servers and skills.

The author of this tool is not an MCP/skill user, so real local trajectories
barely contain them. These fixtures are the ground truth instead: they mirror
the exact record shapes observed in ``~/.claude/projects/*/*.jsonl`` (verified
against a real session that called ``mcp__claude_ai_gh__*`` and one that
invoked two skills), and the tests assert what a profiler can recover from them.
"""

from __future__ import annotations

import json
from pathlib import Path

SESSION = "11111111-2222-3333-4444-555555555555"
CWD = "/home/user/project"
VERSION = "2.1.226"

#: bigger than trajectoriz's 4000-char result truncation, on purpose
FAT_RESULT = json.dumps([{"path": f"src/file_{i}.py", "score": i} for i in range(400)])

SKILL_BODY = (
    "Base directory for this skill: /home/user/project/.claude/skills/demo-skill\n\n"
    "# Demo skill\n\n" + ("Do the thing carefully. " * 300)
)

# display names, as they really appear in mcp_instructions_delta: the slug used
# in mcp__<server>__<tool> is "demo.gh" -> "demo_gh"
MCP_INSTRUCTIONS = {
    "demo.gh": "## demo.gh\nThe GitHub MCP server. " + ("Prefer list_* tools. " * 120),
    "demo_dead": "## demo_dead\nNever called by anyone. " + ("Blah. " * 200),
}

TOOL_SCHEMAS = {
    "mcp__demo_gh__search_code": {
        "description": "Search code across GitHub. " + ("Long description. " * 60),
        "input_schema": {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "query " * 40}},
            "required": ["q"],
        },
    },
    "mcp__demo_gh__get_me": {
        "description": "Get the authenticated user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "mcp__demo_dead__do_nothing": {
        "description": "Never invoked. " + ("Padding. " * 80),
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "string"}},
        },
    },
    "WebFetch": {
        "description": "Fetch a URL.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}},
    },
}

SKILL_LISTING = "\n".join(
    f"- {name}: {desc}"
    for name, desc in [
        ("demo-skill", "Use this skill to do the demo thing. " + "Details. " * 40),
        ("unused-skill", "Never invoked in this session. " + "Details. " * 40),
    ]
)


def _base(kind: str, uuid: str, **extra) -> dict:
    return {
        "type": kind,
        "uuid": uuid,
        "parentUuid": None,
        "isSidechain": False,
        "timestamp": "2026-09-01T10:00:00.000Z",
        "sessionId": SESSION,
        "session_id": SESSION,
        "cwd": CWD,
        "version": VERSION,
        "userType": "external",
        "entrypoint": "cli",
        "gitBranch": "main",
        **extra,
    }


def _assistant(uuid: str, content: list[dict], *, cache_read: int = 20000) -> dict:
    return _base(
        "assistant",
        uuid,
        requestId=f"req_{uuid}",
        message={
            "id": f"msg_{uuid}",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": content,
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 1200,
                "cache_read_input_tokens": cache_read,
                "output_tokens": 90,
            },
        },
    )


def _tool_use(tid: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def _tool_result(uuid: str, tid: str, content: str, *, is_error: bool = False) -> dict:
    return _base(
        "user",
        uuid,
        message={
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
        toolUseResult={"success": not is_error},
    )


def _attachment(uuid: str, att: dict) -> dict:
    return _base("attachment", uuid, attachment=att)


def records() -> list[dict]:
    """The full synthetic session, as a list of JSONL records."""
    out: list[dict] = []

    # --- resident context announcements (attachment records) ---
    out.append(_attachment("a1", {"type": "prompt_snapshot", "systemPrompt": ["You are." * 500]}))
    out.append(
        _attachment(
            "a2",
            {
                "type": "skill_listing",
                "content": SKILL_LISTING,
                "skillCount": 2,
                "isInitial": True,
                "names": ["demo-skill", "unused-skill"],
            },
        )
    )
    out.append(
        _attachment(
            "a3",
            {
                "type": "mcp_instructions_delta",
                "addedNames": list(MCP_INSTRUCTIONS),
                "addedBlocks": list(MCP_INSTRUCTIONS.values()),
                "removedNames": [],
            },
        )
    )
    out.append(
        _attachment(
            "a4",
            {
                "type": "deferred_tools_delta",
                "addedNames": list(TOOL_SCHEMAS),
                "addedLines": [f"{n}: {v['description'][:60]}" for n, v in TOOL_SCHEMAS.items()],
                "removedNames": [],
                "pendingMcpServers": [],
                "failedMcpServers": ["demo_broken"],
            },
        )
    )
    out.append(
        _attachment(
            "a5",
            {
                "type": "deferred_tools_record",
                "entries": [
                    {"name": name, "defer_loading": True, **spec}
                    for name, spec in TOOL_SCHEMAS.items()
                ],
            },
        )
    )

    # --- conversation ---
    out.append(
        _base(
            "user",
            "u1",
            message={"role": "user", "content": "find the auth code on github then run the skill"},
        )
    )

    out.append(
        _assistant(
            "s1",
            [
                _tool_use(
                    "toolu_ts",
                    "ToolSearch",
                    {"query": "select:mcp__demo_gh__search_code,mcp__demo_gh__get_me"},
                )
            ],
        )
    )
    out.append(_tool_result("u2", "toolu_ts", ""))

    out.append(
        _assistant("s2", [_tool_use("toolu_mcp1", "mcp__demo_gh__search_code", {"q": "auth"})])
    )
    out.append(_tool_result("u3", "toolu_mcp1", FAT_RESULT))

    out.append(_assistant("s3", [_tool_use("toolu_mcp2", "mcp__demo_gh__get_me", {})]))
    out.append(_tool_result("u4", "toolu_mcp2", '{"login":"someone"}'))

    out.append(
        _assistant("s4", [_tool_use("toolu_mcp3", "mcp__demo_gh__create_branch", {"name": "x"})])
    )
    out.append(_tool_result("u5", "toolu_mcp3", "Error: branch already exists", is_error=True))

    # skill invocation: result is a stub, the body arrives as the next user turn
    out.append(_assistant("s5", [_tool_use("toolu_skill", "Skill", {"skill": "demo-skill"})]))
    out.append(_tool_result("u6", "toolu_skill", "Launching skill: demo-skill"))
    out.append(
        _base(
            "user",
            "u7",
            promptId="p1",
            message={"role": "user", "content": [{"type": "text", "text": SKILL_BODY}]},
        )
    )

    out.append(_assistant("s6", [_tool_use("toolu_bash", "Bash", {"command": "ls"})]))
    out.append(_tool_result("u8", "toolu_bash", "README.md\n"))

    out.append(_assistant("s7", [{"type": "text", "text": "Done."}]))
    return out


def write_trajectory(directory: Path) -> Path:
    """Write the synthetic session to ``<directory>/<session>.jsonl``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SESSION}.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records()), encoding="utf-8"
    )
    return path

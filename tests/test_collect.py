"""What can a profiler actually recover about MCP and skills from a trajectory?

Each test documents one recoverable fact (or one known loss).
"""

from __future__ import annotations

from pathlib import Path

import trajectoriz as t

from superlean_profiler import ToolEvent, iter_events, split_mcp_name
from tests import _fixtures


def events(parsed) -> list[ToolEvent]:
    record, traj = parsed
    return list(iter_events(record, traj))


def test_split_mcp_name() -> None:
    assert split_mcp_name("mcp__demo_gh__search_code") == ("demo_gh", "search_code")
    assert split_mcp_name("mcp__srv__a__b") == ("srv", "a__b")
    assert split_mcp_name("Bash") is None
    assert split_mcp_name("mcp__srv") is None


def test_mcp_calls_are_attributed_to_their_server(parsed) -> None:
    mcp = [e for e in events(parsed) if e.kind == "mcp"]
    assert [e.name for e in mcp] == ["search_code", "get_me", "create_branch"]
    assert {e.server for e in mcp} == {"demo_gh"}
    assert {e.entity for e in mcp} == {"mcp:demo_gh"}


def test_mcp_arguments_and_results_are_sized(parsed) -> None:
    by_name = {e.name: e for e in events(parsed) if e.kind == "mcp"}
    assert by_name["search_code"].arg_tokens > 0
    assert by_name["get_me"].result_tokens > 0
    # the fat result exceeds trajectoriz's 4000-char truncation...
    assert by_name["search_code"].result_truncated
    # ...and we recover its true size from the truncation marker
    assert by_name["search_code"].result_chars == len(_fixtures.FAT_RESULT)
    assert by_name["search_code"].result_tokens > by_name["get_me"].result_tokens * 10


def test_mcp_errors_are_detected(parsed) -> None:
    by_name = {e.name: e for e in events(parsed) if e.kind == "mcp"}
    assert by_name["create_branch"].is_error
    assert not by_name["get_me"].is_error


def test_skill_invocation_and_injected_body(parsed) -> None:
    skills = [e for e in events(parsed) if e.kind == "skill"]
    assert [e.name for e in skills] == ["demo-skill"]
    skill = skills[0]
    # the Skill tool result is only a stub — the real cost is the injected body
    assert skill.result_tokens < 10
    assert skill.body_tokens == t.estimate_tokens(_fixtures.SKILL_BODY)
    assert skill.total_tokens > 1000
    assert skill.entity == "skill:demo-skill"


def test_toolsearch_and_builtins_are_classified(parsed) -> None:
    kinds = {e.kind for e in events(parsed)}
    assert kinds == {"mcp", "skill", "toolsearch", "builtin"}
    ts = [e for e in events(parsed) if e.kind == "toolsearch"][0]
    assert ts.name == "ToolSearch"
    # its query names the tools that had to be loaded on demand — evidence the
    # tool surface was too large to inline
    assert ts.arg_tokens > 0


def test_session_usage(parsed) -> None:
    from superlean_profiler import session_usage

    record, traj = parsed
    usage = session_usage(record, traj)
    assert usage.session_id == _fixtures.SESSION
    assert usage.agent == "claude"
    assert usage.model_name == "claude-opus-5"
    assert usage.tool_calls == 6
    assert usage.requests == 7
    assert usage.prompt_tokens > 0
    assert usage.cached_tokens > 0


def test_collect_over_records(traj_path: Path) -> None:
    from superlean_profiler import collect

    record = t.TrajectoryRecord("cl-test", "claude", "2026-09-01T10:00:00.000Z", "hi", traj_path)
    sessions, evts = collect([record])
    assert len(sessions) == 1
    assert len(evts) == 6

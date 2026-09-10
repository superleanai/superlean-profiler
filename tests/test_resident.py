"""Resident (always-in-context) cost of MCP servers and skills, measured exactly."""

from __future__ import annotations

from pathlib import Path

import trajectoriz as t

from superlean_profiler import exact_result_sizes, resident_facts
from tests import _fixtures


def test_system_prompt_baseline(traj_path: Path) -> None:
    facts = resident_facts(traj_path)
    assert facts.session_id == _fixtures.SESSION
    assert facts.system_prompt_tokens > 1000


def test_mcp_instruction_blocks_per_server(traj_path: Path) -> None:
    facts = resident_facts(traj_path)
    # display name "demo.gh" is canonicalized to the tool-name slug "demo_gh",
    # otherwise the same server is counted twice
    assert set(facts.mcp_instruction_tokens) == {"demo_gh", "demo_dead"}
    assert facts.mcp_instruction_tokens["demo_gh"] == t.estimate_tokens(
        _fixtures.MCP_INSTRUCTIONS["demo.gh"]
    )


def test_exact_tool_schema_tokens(traj_path: Path) -> None:
    facts = resident_facts(traj_path)
    assert set(facts.tool_schema_tokens) == set(_fixtures.TOOL_SCHEMAS)
    spec = _fixtures.TOOL_SCHEMAS["mcp__demo_gh__search_code"]
    assert facts.tool_schema_tokens["mcp__demo_gh__search_code"] == t.estimate_tokens(
        spec["description"]
    ) + t.estimate_tokens(spec["input_schema"])
    # a chatty tool costs far more than a terse one, every request it is loaded
    assert facts.tool_schema_tokens["mcp__demo_gh__search_code"] > (
        10 * facts.tool_schema_tokens["mcp__demo_gh__get_me"]
    )


def test_listing_cost_is_distinct_from_schema_cost(traj_path: Path) -> None:
    """Deferred tools cost one line each until loaded — that saving is measurable."""
    facts = resident_facts(traj_path)
    assert set(facts.tool_listing_tokens) == set(_fixtures.TOOL_SCHEMAS)
    tool = "mcp__demo_gh__search_code"
    assert facts.tool_schema_tokens[tool] > facts.tool_listing_tokens[tool]
    # both views are available per server
    assert facts.server_schema_tokens()["demo_gh"] > 0
    assert facts.server_resident_tokens()["demo_gh"] > 0


def test_server_resident_cost_and_dead_weight(traj_path: Path) -> None:
    facts = resident_facts(traj_path)
    per_server = facts.server_resident_tokens()
    assert set(per_server) == {"demo_gh", "demo_dead"}
    # demo_dead is never called anywhere in the session, yet it is resident
    assert per_server["demo_dead"] > 100
    assert facts.failed_mcp_servers == {"demo_broken"}
    assert facts.mcp_servers == {"demo_gh", "demo_dead"}


def test_skill_listing_is_resident_even_for_unused_skills(traj_path: Path) -> None:
    facts = resident_facts(traj_path)
    assert facts.skill_names == {"demo-skill", "unused-skill"}
    assert facts.skill_listing_tokens == t.estimate_tokens(_fixtures.SKILL_LISTING)


def test_exact_result_sizes_and_error_flag(traj_path: Path) -> None:
    sizes = exact_result_sizes(traj_path)
    # untruncated, unlike the public API
    assert sizes["toolu_mcp1"][0] == t.estimate_tokens(_fixtures.FAT_RESULT)
    assert sizes["toolu_mcp3"][1] is True
    assert sizes["toolu_mcp2"][1] is False


def test_dead_weight_report_is_computable(traj_path: Path, parsed) -> None:
    """The headline finding: resident tokens for a server with zero calls."""
    from superlean_profiler import iter_events

    record, traj = parsed
    called = {e.server for e in iter_events(record, traj) if e.kind == "mcp"}
    facts = resident_facts(traj_path)
    waste = {s: tok for s, tok in facts.server_resident_tokens().items() if s not in called}
    assert set(waste) == {"demo_dead"}
    assert waste["demo_dead"] > 0

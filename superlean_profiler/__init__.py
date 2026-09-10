"""superlean-profiler — find which MCP servers and skills eat your tokens."""

from __future__ import annotations

from ._claude_raw import (
    RESIDENT_ATTACHMENTS,
    ResidentFacts,
    canonical_server,
    exact_result_sizes,
    resident_facts,
)
from ._collect import (
    SessionUsage,
    ToolEvent,
    collect,
    iter_events,
    iter_tool_calls,
    session_usage,
    split_mcp_name,
)

__all__ = [
    "RESIDENT_ATTACHMENTS",
    "ResidentFacts",
    "SessionUsage",
    "ToolEvent",
    "canonical_server",
    "collect",
    "exact_result_sizes",
    "iter_events",
    "iter_tool_calls",
    "resident_facts",
    "session_usage",
    "split_mcp_name",
]
__version__ = "0.1.0"

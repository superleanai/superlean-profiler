# superlean-profiler

Profiler for coding agents: reads your past agent trajectories and reports **which MCP
servers and skills eat your tokens**, then says what to remove or refactor.

The interesting cost is not what MCP calls consume — it is what unused servers and skills
consume *anyway*. Tool schemas, per-server instruction blocks and the skill listing sit in
**every single request** whether or not anything ever calls them. This tool measures that
separately from actual use, so "used in 89 of 1966 sessions" becomes a number you can act on.

Trajectories are read with [`trajectoriz`](https://github.com/monperrus/trajectoriz), so
Claude Code, Codex, Copilot, OpenCode and Hermes sessions are all covered for usage cost.
Resident cost is currently measured for Claude Code only (see [Status](#status)).

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
slprof                      # profile every trajectory, full report
slprof mcp                  # MCP servers, then per-tool drill-down
slprof skills               # skills only
slprof advice               # ranked findings only
slprof --local              # only trajectories of the current directory
slprof --agent claude --since 2026-06-01 --limit 200
slprof --json               # machine-readable, same data
```

## Example

Real output over 15 407 sessions (21 s, parallel, incremental cache). Two internal server
names are redacted:

```
15407 sessions, 191959 requests, 30708.3M tokens  [agent_probe 10301, claude 3328, copilot 776, codex 554, copilot_db 424, hermes 24]
resident context measured in 3328 session(s)

MCP SERVER                    CALLS  USED/SEEN  RES/REQ  RESIDENT  ACTIVE   TOTAL
----------------------------  -----  ---------  -------  --------  ------  ------
claude_ai_gh                    385    89/1966      435    105.3M  276.0k  105.6M
claude-in-chrome                 46     29/763      464     43.5M    4.7k   43.5M
internal_server_1                 0     0/1511       23      2.8M       0    2.8M
internal_server_2                 0      0/640       21      1.5M       0    1.5M
claude_ai_markdown_documents      0      0/873       27      1.3M       0    1.3M
claude_ai_Google_Calendar         0      0/129       25    621.4k       0  621.4k

MCP TOOL                            CALLS  ERR  TOK/USE  P95 RESULT  ACTIVE
----------------------------------  -----  ---  -------  ----------  ------
brave-search/brave_search             643    4      753        2.4k  484.3k
claude_ai_gh/search_code               41    4     1.7k        8.8k   68.1k
claude_ai_gh/get_file_contents         41    4     1.3k        4.4k   52.8k

SKILL                     USES  USED/SEEN  RES/REQ  RESIDENT   BODY  TOTAL
------------------------  ----  ---------  -------  --------  -----  -----
claude-api                  22    22/2555      269     47.1M   2.9M  50.0M
dataviz                      5     5/1020      287     33.4M   8.9k  33.4M
code-review                  0     0/2423      102     24.8M      0  24.8M

SEV   ENTITY            ACTION   SAVES  WHY
----  ----------------  ------  ------  ----------------------------------------------------------------------
high  claude_ai_gh      defer   100.5M  MCP server used in 89/1966 sessions (4.5%) yet resident in all of them
high  claude-api        defer    46.7M  skill used in 22/2555 sessions (0.9%) yet resident in all of them
high  code-review       remove   24.8M  skill resident in 2423 session(s) (102 tok/request), never called once
```

`claude_ai_gh` cost 276k tokens in actual calls and **105M** tokens in merely being present —
a factor of 380. Meanwhile `brave_search`, the busiest tool by call count, is a rounding
error. That asymmetry is the whole point of the tool.

## Reading the numbers

| Column | Meaning |
|---|---|
| `CALLS` | tool calls / skill invocations across all profiled sessions |
| `USED/SEEN` | sessions that used it / sessions it was resident in |
| `RES/REQ` | tokens it adds to **every request** (median across sessions) |
| `RESIDENT` | `RES/REQ × requests`, summed — the cache-read view of the bill |
| `ACTIVE` | call arguments + results, plus injected `SKILL.md` bodies for skills |
| `P95 RESULT` | 95th-percentile result size: fat-result detection |

`RESIDENT` is what you are billed as cache reads, which are cheaper per token than fresh
input — do not compare it one-to-one against `ACTIVE`. `USED/SEEN` denominators only count
sessions where resident context could be measured.

## How it works

```
trajectoriz.parse_record()  →  steps: messages, tool calls, results        (usage side)
raw JSONL attachment records →  tool schemas, MCP instructions, skills     (resident side)
```

Usage side, via the public trajectoriz API for every agent format: MCP server/tool split
from `mcp__<server>__<tool>`, argument and result tokens, error flags, skill invocations —
and the exact cost of an injected skill body, which arrives as the user turn right after the
`Skill` call.

Resident side, for Claude Code, from `attachment` records that trajectoriz does not surface:
`deferred_tools_record` (exact per-tool schemas), `deferred_tools_delta` (deferred listing,
failed servers), `mcp_instructions_delta` (per-server instruction blocks), `skill_listing`
(each skill's own description lines), `prompt_snapshot` (system-prompt baseline).

`tests/_fixtures.py` builds a synthetic Claude Code session containing MCP calls, a fat
result, an MCP error, a skill invocation with its body, a `ToolSearch` and every resident
record type; the tests assert exactly what a profiler can and cannot recover from it.

Two things the raw data forces: MCP server names must be canonicalized (`mcp_instructions_delta`
says `claude.ai gh`, tool names say `claude_ai_gh`, else the same server is counted twice),
and listing cost must stay separate from schema cost — with tool deferral a server costs one
line per tool per request until a `ToolSearch` loads the real schema.

## Status

Working: collection, aggregation, advice rules, `slprof` CLI. Resident cost is measured for
Claude Code; other agents report usage cost only.

Next: `_inventory.py` (servers and skills that are configured but appear in no session at
all, so never show up above) and `--probe` (size an MCP server's schemas via `tools/list`).

## License

GNU Affero General Public License v3.0 or later — see [LICENSE](LICENSE).

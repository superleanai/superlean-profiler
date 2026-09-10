"""Parallel profiling of many trajectories into per-session facts."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import trajectoriz as t

from ._claude_raw import ResidentFacts, resident_facts
from ._collect import SessionUsage, ToolEvent, iter_events, session_usage

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "superlean-profiler"


@dataclass
class SessionFacts:
    """Everything we know about one session."""

    usage: SessionUsage
    events: list[ToolEvent] = field(default_factory=list)
    resident: ResidentFacts | None = None


def _profile_one(record: t.TrajectoryRecord) -> SessionFacts | None:
    traj = t.parse_record(record, cache_dir=str(CACHE_DIR))
    if traj is None:
        return None
    resident = None
    source = record.source
    if record.agent == "claude" and isinstance(source, (str, Path)) and Path(source).is_file():
        resident = resident_facts(source)
    return SessionFacts(
        usage=session_usage(record, traj),
        events=list(iter_events(record, traj)),
        resident=resident,
    )


def select_records(
    *,
    local: bool = False,
    agents: tuple[str, ...] = (),
    since: str = "",
    limit: int = 0,
) -> list[t.TrajectoryRecord]:
    records = []
    for record in t.iter_records(cwd=os.getcwd() if local else None):
        if agents and record.agent not in agents:
            continue
        if since and record.timestamp < since:
            continue
        records.append(record)
    records.sort(key=lambda r: r.timestamp, reverse=True)
    return records[:limit] if limit else records


def profile(records: list[t.TrajectoryRecord], jobs: int = 0) -> list[SessionFacts]:
    """Parse records (in parallel) into per-session facts."""
    jobs = jobs or min(32, (os.cpu_count() or 4))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[SessionFacts] = []
    if jobs <= 1 or len(records) < 4:
        for record in records:
            if (facts := _profile_one(record)) is not None:
                out.append(facts)
        return out
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for facts in pool.map(_profile_one, records, chunksize=8):
            if facts is not None:
                out.append(facts)
    return out

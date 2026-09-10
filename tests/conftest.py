from __future__ import annotations

from pathlib import Path

import pytest
import trajectoriz as t

from tests import _fixtures


@pytest.fixture(scope="session")
def traj_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _fixtures.write_trajectory(tmp_path_factory.mktemp("mcp-skills"))


@pytest.fixture(scope="session")
def parsed(traj_path: Path) -> tuple[t.TrajectoryRecord, t.ParsedTrajectory]:
    traj = t.parse_claude_trajectory(traj_path)
    record = t.TrajectoryRecord(
        id="cl-test",
        agent="claude",
        timestamp="2026-09-01T10:00:00.000Z",
        first_msg="find the auth code",
        source=traj_path,
    )
    return record, traj

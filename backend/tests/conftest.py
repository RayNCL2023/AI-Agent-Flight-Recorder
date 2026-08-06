"""Test fixtures. Environment must be pinned before the app package is imported."""

import os
import tempfile
import time
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="afr-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AFR_MODE"] = "replay"
os.environ["FILE_READER_ROOT"] = str(Path(__file__).resolve().parent.parent / "sample_data")

import pytest
from fastapi.testclient import TestClient

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def wait_for_run(client: TestClient, run_id: str, timeout: float = 30.0) -> dict:
    """Poll until the run settles (completed/failed)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/runs/{run_id}").json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} did not settle within {timeout}s")


def wait_for_branch(client: TestClient, branch_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/branches/{branch_id}/timeline").json()
        if data["branch"]["status"] in ("completed", "failed"):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"branch {branch_id} did not settle within {timeout}s")

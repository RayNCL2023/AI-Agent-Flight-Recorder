"""Bundled trace library: seeding, stats, experiment replay, determinism."""

import time

from .conftest import wait_for_branch

EXPECTED_SLUG_TITLES = {
    "Research a startup",
    "Compare two programming languages",
    "Investigate a bug",
    "Plan a trip",
    "Summarise documentation",
}


def _library(client) -> list[dict]:
    return [r for r in client.get("/api/runs").json() if r["source"] == "recorded"]


def _final_answer(events: list[dict]) -> str | None:
    for e in reversed(events):
        if e["type"] == "completion":
            return e["payload"]["content"]
    return None


def test_library_is_seeded_with_stats(client):
    library = _library(client)
    titles = {r["title"] for r in library}
    assert EXPECTED_SLUG_TITLES <= titles
    for r in library:
        if r["title"] not in EXPECTED_SLUG_TITLES:
            continue
        assert r["description"]
        assert r["experiments"], "every library trace ships recorded experiments"
        assert r["tools_used"]
        assert r["stats"]["events"] > 0
        assert r["stats"]["tokens"] > 0
        assert r["stats"]["cost_usd"] > 0
        assert r["stats"]["duration_ms"] > 0
        assert r["status"] == "completed"


def _root_branch(client, run_id: str) -> dict:
    run = client.get(f"/api/runs/{run_id}").json()
    return next(b for b in run["branches"] if b["parent_branch_id"] is None)


def _fork_experiment(client, run: dict, exp: dict) -> dict:
    root = _root_branch(client, run["id"])
    res = client.post(
        f"/api/branches/{root['id']}/fork",
        json={
            "fork_seq": exp["fork_seq"],
            "name": exp["title"],
            "edited_prompt": exp["edited_prompt"],
            "tool_overrides": exp["tool_overrides"],
        },
    )
    assert res.status_code == 201, res.text
    return wait_for_branch(client, res.json()["id"])


def test_experiment_fork_replays_to_recorded_divergence(client):
    run = next(r for r in _library(client) if r["title"] == "Plan a trip")
    exp = next(e for e in run["experiments"] if e["id"] == "trip-storm")

    root = _root_branch(client, run["id"])
    base_events = client.get(f"/api/branches/{root['id']}/timeline").json()["events"]
    base_answer = _final_answer(base_events)

    forked = _fork_experiment(client, run, exp)
    assert forked["branch"]["status"] == "completed"
    answer = _final_answer(forked["events"])
    assert answer and answer != base_answer, "the storm experiment must diverge"
    assert "thunderstorms" in answer

    # Recorded post-mortem is attached with explicit provenance.
    deadline = time.time() + 10
    branch = forked["branch"]
    while time.time() < deadline and branch["label"] == "unlabeled":
        time.sleep(0.1)
        branch = client.get(f"/api/branches/{branch['id']}/timeline").json()["branch"]
    assert branch["label"] == exp["recorded_label"]
    assert branch["diagnosis"] == exp["recorded_diagnosis"]
    assert branch["analysis_source"] == "recorded"


def test_control_replay_experiment_is_deterministic(client):
    run = next(r for r in _library(client) if r["title"] == "Summarise documentation")
    exp = next(e for e in run["experiments"] if e["id"] == "docs-control-replay")

    root = _root_branch(client, run["id"])
    base = client.get(f"/api/branches/{root['id']}/timeline").json()["events"]
    forked = _fork_experiment(client, run, exp)
    assert forked["branch"]["status"] == "completed"

    def signature(events):
        return [
            (e["seq"], e["type"], {k: v for k, v in e["payload"].items() if k != "cached"})
            for e in events
        ]

    assert signature(forked["events"]) == signature(base)


def test_custom_unrecorded_fork_fails_honestly_via_api(client):
    run = next(r for r in _library(client) if r["title"] == "Research a startup")
    root = _root_branch(client, run["id"])
    res = client.post(
        f"/api/branches/{root['id']}/fork",
        json={"fork_seq": 1, "edited_prompt": "Research the startup OpenAI instead."},
    )
    assert res.status_code == 201, res.text
    forked = wait_for_branch(client, res.json()["id"])
    types = [e["type"] for e in forked["events"]]
    assert "replay_miss" in types
    assert "completion" not in types
    assert forked["branch"]["status"] == "failed"

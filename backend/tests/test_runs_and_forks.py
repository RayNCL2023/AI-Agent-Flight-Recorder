"""End-to-end: run capture, determinism, fork/replay divergence, diff, export."""

from .conftest import wait_for_branch, wait_for_run

PROMPT = "What is 2+2*3? Also what's the weather in Paris?"


def _signature(events: list[dict]) -> list[tuple]:
    """Deterministic fingerprint of a timeline: types, names, payloads."""
    return [(e["seq"], e["type"], e["name"], str(e["payload"])) for e in events]


def _create_and_wait(client, prompt: str = PROMPT, seed: int = 42):
    run = client.post("/api/runs", json={"prompt": prompt, "seed": seed}).json()
    wait_for_run(client, run["id"])
    root = run["branches"][0]
    timeline = wait_for_branch(client, root["id"])
    return run, timeline


def test_run_captures_full_trace(client):
    run, timeline = _create_and_wait(client)
    types = [e["type"] for e in timeline["events"]]
    assert types[0] == "run_started"
    assert "tool_call" in types and "tool_result" in types
    assert types[-1] == "completion"
    assert timeline["branch"]["status"] == "completed"
    # Every event is causally chained to its predecessor.
    events = timeline["events"]
    for prev, cur in zip(events, events[1:]):
        assert cur["parent_event_id"] == prev["id"]
    # Token/cost accounting is present on LLM events.
    assert timeline["stats"]["tokens_in"] > 0
    assert timeline["stats"]["cost_usd"] > 0


def test_identical_runs_are_deterministic(client):
    _, t1 = _create_and_wait(client, seed=7)
    _, t2 = _create_and_wait(client, seed=7)
    assert _signature(t1["events"]) == _signature(t2["events"])


def test_fork_with_tool_override_diverges(client):
    run, timeline = _create_and_wait(client)
    root_id = timeline["branch"]["id"]
    events = timeline["events"]

    calc_result = next(
        e for e in events
        if e["type"] == "tool_result" and e["payload"]["tool"] == "calculator"
    )
    fork = client.post(
        f"/api/branches/{root_id}/fork",
        json={
            "fork_seq": calc_result["seq"] + 1,
            "name": "what-if-calc-lied",
            "tool_overrides": {
                calc_result["id"]: {"expression": "2+2*3", "result": 999}
            },
        },
    )
    assert fork.status_code == 201, fork.text
    fork_timeline = wait_for_branch(client, fork.json()["id"])

    # Shared history below the fork point is inherited, not copied.
    fork_seq = calc_result["seq"] + 1
    inherited = [e for e in fork_timeline["events"] if e["seq"] < fork_seq]
    original = [e for e in events if e["seq"] < fork_seq]
    assert [e["id"] for e in inherited] == [e["id"] for e in original]

    # The overridden value propagates into the fork's final answer.
    completion = fork_timeline["events"][-1]
    assert completion["type"] == "completion"
    assert "999" in completion["payload"]["content"]
    original_completion = events[-1]["payload"]["content"]
    assert completion["payload"]["content"] != original_completion


def test_fork_with_edited_prompt(client):
    run, timeline = _create_and_wait(client)
    root_id = timeline["branch"]["id"]
    fork = client.post(
        f"/api/branches/{root_id}/fork",
        json={"fork_seq": 1, "edited_prompt": "What is 100/4? No other questions."},
    ).json()
    fork_timeline = wait_for_branch(client, fork["id"])
    completion = fork_timeline["events"][-1]
    assert "25" in completion["payload"]["content"]


def test_diff_marks_divergence(client):
    run, timeline = _create_and_wait(client)
    root_id = timeline["branch"]["id"]
    events = timeline["events"]
    fork = client.post(
        f"/api/branches/{root_id}/fork",
        json={"fork_seq": events[-1]["seq"], "edited_prompt": None},
    ).json()
    wait_for_branch(client, fork["id"])
    diff = client.get(f"/api/branches/{fork['id']}/diff").json()
    kinds = {e["kind"] for e in diff["entries"]}
    assert "same" in kinds
    assert diff["fork_seq"] == events[-1]["seq"]


def test_branch_gets_labeled(client):
    _, timeline = _create_and_wait(client)
    branch = wait_for_branch(client, timeline["branch"]["id"])["branch"]
    assert branch["label"] in ("success", "hallucination", "loop", "failed")
    assert branch["diagnosis"]


def test_export_import_roundtrip(client):
    run, timeline = _create_and_wait(client)
    export = client.get(f"/api/runs/{run['id']}/export").json()
    assert export["events"], "export should contain events"

    # Re-import under fresh ids by deleting the original first.
    client.delete(f"/api/runs/{run['id']}")
    imported = client.post("/api/runs/import", json=export)
    assert imported.status_code == 201, imported.text
    round_tripped = client.get(f"/api/runs/{run['id']}/export").json()
    assert len(round_tripped["events"]) == len(export["events"])

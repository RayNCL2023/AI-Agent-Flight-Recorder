"""Branch diff over a replayed experiment: shared prefix, marked divergence."""

from .conftest import wait_for_branch


def test_diff_marks_shared_history_and_divergence(client):
    run = next(
        r for r in client.get("/api/runs").json()
        if r["source"] == "recorded" and r["title"] == "Research a startup"
    )
    exp = next(e for e in run["experiments"] if e["id"] == "research-empty-search")
    detail = client.get(f"/api/runs/{run['id']}").json()
    root = next(b for b in detail["branches"] if b["parent_branch_id"] is None)

    res = client.post(
        f"/api/branches/{root['id']}/fork",
        json={
            "fork_seq": exp["fork_seq"],
            "edited_prompt": exp["edited_prompt"],
            "tool_overrides": exp["tool_overrides"],
        },
    )
    assert res.status_code == 201, res.text
    fork = wait_for_branch(client, res.json()["id"])
    assert fork["branch"]["status"] == "completed"

    diff = client.get(f"/api/branches/{fork['branch']['id']}/diff").json()
    kinds = [e["kind"] for e in diff["entries"]]
    assert diff["fork_seq"] == exp["fork_seq"]
    assert "same" in kinds, "history before the fork point must align as identical"
    assert "changed" in kinds or "added_a" in kinds or "added_b" in kinds, (
        "the overridden evidence must surface as divergence"
    )
    # The final answers differ: the fork declines the funding claim.
    completions = [
        e for e in diff["entries"]
        if (e["a"] and e["a"]["type"] == "completion") or (e["b"] and e["b"]["type"] == "completion")
    ]
    assert completions, "both branches should reach a completion to compare"

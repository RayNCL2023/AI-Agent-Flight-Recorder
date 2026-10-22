"""API honesty: mode gating, immutable library traces, v2 export round-trip."""

from app.db import SessionLocal
from app.models import LLMCacheEntry, Run, ToolCacheEntry

from .util import record_scripted_run


def test_meta_reports_replay_mode(client):
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "replay"
    assert meta["live_available"] is False
    assert meta["model"] == "recorded"


def test_new_runs_are_refused_in_replay_mode(client):
    res = client.post("/api/runs", json={"prompt": "anything at all"})
    assert res.status_code == 409
    assert "Replay Mode" in res.json()["detail"]


def test_recorded_traces_cannot_be_deleted(client):
    run_id, _ = record_scripted_run()
    res = client.delete(f"/api/runs/{run_id}")
    assert res.status_code == 409
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_run_list_carries_stats(client):
    run_id, _ = record_scripted_run()
    runs = client.get("/api/runs").json()
    item = next(r for r in runs if r["id"] == run_id)
    assert item["source"] == "recorded"
    assert item["stats"]["events"] > 0
    assert item["stats"]["tokens"] > 0
    assert "web_search" in item["tools_used"] or item["tools_used"] == [], (
        "tools_used is populated by the recording harness/seeds; empty is legal here"
    )


def test_export_import_v2_roundtrips_caches(client):
    run_id, _ = record_scripted_run()
    export = client.get(f"/api/runs/{run_id}/export").json()
    assert export["version"] == 2
    assert export["events"]
    assert export["llm_cache"], "bundle must carry the LLM completion cache"
    assert export["tool_cache"], "bundle must carry the tool cache"

    db = SessionLocal()
    try:
        # Simulate moving the bundle to a fresh instance: delete the original
        # directly (the API rightly refuses to delete recorded traces).
        run = db.get(Run, run_id)
        db.delete(run)
        db.query(ToolCacheEntry).filter_by(run_id=run_id).delete()
        db.query(LLMCacheEntry).filter_by(run_id=run_id).delete()
        db.commit()
    finally:
        db.close()

    imported = client.post("/api/runs/import", json=export)
    assert imported.status_code == 201, imported.text
    round_tripped = client.get(f"/api/runs/{run_id}/export").json()
    assert len(round_tripped["events"]) == len(export["events"])
    assert len(round_tripped["llm_cache"]) == len(export["llm_cache"])
    assert len(round_tripped["tool_cache"]) == len(export["tool_cache"])

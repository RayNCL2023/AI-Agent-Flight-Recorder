"""LLM completion cache: key stability, round-trip, first-write-wins."""

from app.agent.llm_cache import cache_key, lookup, store
from app.db import SessionLocal
from app.models import Run


MESSAGES = [
    {"role": "system", "content": "You are a precise research agent."},
    {"role": "user", "content": "Compare Python and Rust."},
]


def test_cache_key_is_stable_and_content_sensitive():
    k1 = cache_key("m1", 42, MESSAGES)
    k2 = cache_key("m1", 42, [dict(m) for m in MESSAGES])
    assert k1 == k2, "identical conversation state must hash identically"
    assert cache_key("m1", 43, MESSAGES) != k1, "seed is part of the state"
    assert cache_key("m2", 42, MESSAGES) != k1, "model is part of the state"
    changed = MESSAGES[:-1] + [{"role": "user", "content": "Compare Python and Go."}]
    assert cache_key("m1", 42, changed) != k1, "message content is part of the state"


def test_store_lookup_roundtrip_and_first_write_wins(client):
    db = SessionLocal()
    try:
        run = Run(title="t", prompt="p", model="m", seed=1, source="recorded")
        db.add(run)
        db.commit()

        key = cache_key("m", 1, MESSAGES)
        assert lookup(db, run.id, key) is None

        response = {"content": "answer", "tool_calls": [], "tokens_in": 10}
        store(db, run.id, key, response)
        assert lookup(db, run.id, key) == response

        store(db, run.id, key, {"content": "OVERWRITE ATTEMPT"})
        assert lookup(db, run.id, key) == response, "cache must be first-write-wins"
    finally:
        db.close()

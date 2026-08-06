import pytest

from app.agent.tools.calculator import run_calculator
from app.agent.tools.weather import run_weather
from app.agent.tools.web_search import run_web_search


def test_calculator_arithmetic():
    assert run_calculator({"expression": "(2+3)*4"}, 0)["result"] == 20
    assert run_calculator({"expression": "10/4"}, 0)["result"] == 2.5
    assert run_calculator({"expression": "2**10"}, 0)["result"] == 1024


@pytest.mark.parametrize(
    "expr",
    ["__import__('os')", "open('x')", "a+b", "2**999999", "[1,2]", "'x'*3"],
)
def test_calculator_rejects_unsafe(expr):
    with pytest.raises((ValueError, SyntaxError)):
        run_calculator({"expression": expr}, 0)


def test_weather_is_seed_deterministic():
    a = run_weather({"city": "Paris"}, 42)
    b = run_weather({"city": "Paris"}, 42)
    c = run_weather({"city": "Paris"}, 7)
    assert a == b
    assert a != c


def test_web_search_ranks_relevant_docs():
    out = run_web_search({"query": "how tall is the Eiffel Tower"}, 0)
    assert out["results"], "expected at least one result"
    assert "Eiffel" in out["results"][0]["title"]


def test_web_search_empty_for_nonsense():
    out = run_web_search({"query": "zzqx frobnicate glomp"}, 0)
    assert out["results"] == []

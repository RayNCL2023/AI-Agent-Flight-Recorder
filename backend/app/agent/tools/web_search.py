"""Deterministic web search.

Live web search would make replays non-reproducible and require API keys, so
this tool searches a small built-in document corpus with BM25-ish scoring.
The interface (query -> ranked {title,url,snippet}) matches a real search API,
so swapping in Bing/Tavily/SerpAPI later is a one-file change — results would
then be pinned by the tool cache, keeping replays deterministic anyway.
"""

import re
from typing import Any

_CORPUS: list[dict[str, str]] = [
    {
        "title": "Eiffel Tower — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
        "text": "The Eiffel Tower is a wrought-iron lattice tower in Paris, France. "
        "It is 330 metres (1,083 ft) tall and was completed in 1889 for the World's Fair.",
    },
    {
        "title": "Mount Everest — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Mount_Everest",
        "text": "Mount Everest is Earth's highest mountain above sea level, at 8,848.86 m "
        "(29,031.7 ft), located in the Himalayas on the China–Nepal border.",
    },
    {
        "title": "Speed of light — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Speed_of_light",
        "text": "The speed of light in vacuum is exactly 299,792,458 metres per second. "
        "It is the upper limit for the speed of matter and information.",
    },
    {
        "title": "Python (programming language) — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "text": "Python is a high-level, general-purpose programming language created by "
        "Guido van Rossum and first released in 1991. Python 3.13 was released in October 2024.",
    },
    {
        "title": "Tokyo — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Tokyo",
        "text": "Tokyo is the capital of Japan and the most populous metropolitan area in "
        "the world, with over 37 million residents in the greater Tokyo area.",
    },
    {
        "title": "Moon landing — Apollo 11",
        "url": "https://en.wikipedia.org/wiki/Apollo_11",
        "text": "Apollo 11 was the first crewed mission to land on the Moon, on 20 July 1969. "
        "Neil Armstrong and Buzz Aldrin walked on the lunar surface.",
    },
    {
        "title": "GDP of France — World Bank",
        "url": "https://data.worldbank.org/country/france",
        "text": "France's gross domestic product (GDP) was approximately 3.03 trillion USD "
        "in 2023, making it the seventh largest economy in the world.",
    },
    {
        "title": "Amazon rainforest — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Amazon_rainforest",
        "text": "The Amazon rainforest covers about 5.5 million square kilometres and "
        "contains an estimated 390 billion individual trees.",
    },
    {
        "title": "Marie Curie — Biography",
        "url": "https://en.wikipedia.org/wiki/Marie_Curie",
        "text": "Marie Curie was a physicist and chemist who conducted pioneering research "
        "on radioactivity. She won Nobel Prizes in Physics (1903) and Chemistry (1911).",
    },
    {
        "title": "Great Barrier Reef — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Great_Barrier_Reef",
        "text": "The Great Barrier Reef is the world's largest coral reef system, "
        "stretching over 2,300 kilometres off the coast of Queensland, Australia.",
    },
    {
        "title": "Anthropic — company overview",
        "url": "https://en.wikipedia.org/wiki/Anthropic",
        "text": "Anthropic is an AI safety company founded in 2021 by Dario Amodei and "
        "Daniela Amodei. It develops the Claude family of large language models and "
        "focuses on building reliable, interpretable and steerable AI systems.",
    },
    {
        "title": "Anthropic funding and investors",
        "url": "https://example.com/anthropic-funding",
        "text": "Anthropic has raised billions in venture funding, including a 2023 "
        "agreement with Amazon worth up to 4 billion USD and investment from Google. "
        "The startup's total raised exceeds 7 billion USD across multiple rounds.",
    },
    {
        "title": "Mistral AI — company overview",
        "url": "https://en.wikipedia.org/wiki/Mistral_AI",
        "text": "Mistral AI is a French startup founded in 2023 by former DeepMind and "
        "Meta researchers. It builds open-weight large language models and raised "
        "600 million EUR in 2024 at a valuation near 6 billion EUR.",
    },
    {
        "title": "Rust (programming language) — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Rust_(programming_language)",
        "text": "Rust is a systems programming language that guarantees memory safety "
        "without garbage collection through ownership and borrowing. Stable since 2015, "
        "its async ecosystem (Tokio, hyper) powers very high-throughput network servers.",
    },
    {
        "title": "Go (programming language) — Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Go_(programming_language)",
        "text": "Go is a statically typed language designed at Google and released in "
        "2009. Goroutines and channels make concurrent servers simple to write; it is "
        "garbage collected, compiles fast, and deploys as a single static binary.",
    },
    {
        "title": "SQLite Frequently Asked Questions — database is locked",
        "url": "https://sqlite.org/faq.html",
        "text": "The SQLITE_BUSY 'database is locked' error occurs when one connection "
        "holds a write transaction while another tries to write. Long-running write "
        "transactions are the usual cause; enabling WAL journal mode and setting a "
        "busy_timeout are the standard fixes.",
    },
    {
        "title": "Tokyo travel guide — autumn highlights",
        "url": "https://example.com/tokyo-travel-november",
        "text": "Top Tokyo attractions include the Senso-ji temple in Asakusa, Shibuya "
        "crossing, teamLab Planets and the Meiji Shrine. November brings autumn foliage, "
        "mild days and low rainfall, making it one of the best months to visit.",
    },
    {
        "title": "Python for web services — throughput notes",
        "url": "https://example.com/python-async-apis",
        "text": "Python with asyncio and frameworks like FastAPI handles I/O-bound API "
        "workloads well, though the GIL limits CPU-bound parallelism and raw throughput "
        "trails compiled languages. Developer velocity and ecosystem are its strengths.",
    },
]

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def run_web_search(args: dict[str, Any], _seed: int) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    q_tokens = set(_tokens(query))
    scored: list[tuple[float, dict[str, str]]] = []
    for doc in _CORPUS:
        doc_tokens = _tokens(doc["title"] + " " + doc["text"])
        overlap = sum(1 for t in doc_tokens if t in q_tokens)
        if overlap:
            scored.append((overlap / (len(doc_tokens) ** 0.5), doc))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["url"]))
    results = [
        {"title": d["title"], "url": d["url"], "snippet": d["text"][:220]}
        for _score, d in scored[:3]
    ]
    return {
        "query": query,
        "results": results,
        "total": len(results),
        "source": "offline_corpus",
    }

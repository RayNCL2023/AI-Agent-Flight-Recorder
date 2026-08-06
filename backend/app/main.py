"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import branches, runs, stream
from .bundles import load_bundled_traces
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=get_settings().log_level.upper())
    init_db()
    load_bundled_traces()
    yield


app = FastAPI(
    title="Agent Flight Recorder",
    description="Time-travel debugger for LLM agents: immutable event log, "
    "branching timelines, deterministic fork & replay.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(branches.router)
app.include_router(stream.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "mode": settings.mode,
    }


@app.get("/api/meta", tags=["meta"])
def meta() -> dict:
    """Execution-mode facts the UI must surface truthfully."""
    settings = get_settings()
    return {
        "mode": settings.mode,
        "live_available": settings.live_available,
        "model": settings.llm_model if settings.live_available else "recorded",
        "version": __version__,
    }

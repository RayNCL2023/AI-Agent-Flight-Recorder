"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import branches, runs, stream
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=get_settings().log_level.upper())
    init_db()
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

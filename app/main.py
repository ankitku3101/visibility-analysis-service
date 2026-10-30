from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.analysis.runner import mark_interrupted
from app.api import analyses, datasets, health, reports
from app.config import get_settings
from app.db import connect, init_db
from app.errors import register_error_handlers
from app.llm.client import get_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = get_settings().db_path
    init_db(db_path)
    conn = connect(db_path)
    try:
        mark_interrupted(conn)
    finally:
        conn.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kasparro AI Visibility Analysis Service",
        description="Imports saved AI answers, analyses how Kasparro appears, and controls report review and export.",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    # The analysis API builds its LLM client through this, so tests can swap in a scripted StubClient.
    app.state.client_factory = get_client
    app.include_router(health.router)
    app.include_router(datasets.router)
    app.include_router(analyses.router)
    app.include_router(reports.router)
    return app


app = create_app()

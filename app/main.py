from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import datasets, health
from app.config import get_settings
from app.db import init_db
from app.errors import register_error_handlers
from app.llm.client import get_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_settings().db_path)
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
    return app


app = create_app()

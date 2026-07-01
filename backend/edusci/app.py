from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from rq import Queue

from edusci.api.routes import router
from edusci.analysis.storage import LocalObjectStore
from edusci.integrations.qwen import QwenProvider
from edusci.integrations.retrieval import OpenResearchRetriever
from edusci.memory.database import build_session_factory


def create_app(
    database_url: str | None = None,
    task_mode: str | None = None,
    storage_root: str | Path | None = None,
    model_provider=None,
    task_queue=None,
) -> FastAPI:
    resolved_database = database_url or os.getenv(
        "DATABASE_URL", "sqlite+pysqlite:///./data/edusci.db"
    )

    resolved_provider = model_provider
    if resolved_provider is None and os.getenv("DASHSCOPE_API_KEY", "").strip():
        resolved_provider = QwenProvider(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            base_url=os.getenv(
                "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            generation_model=os.getenv("QWEN_GENERATION_MODEL", "qwen-plus"),
            review_model=os.getenv("QWEN_REVIEW_MODEL", "qwen-max"),
        )

    resolved_task_mode = task_mode or os.getenv("TASK_MODE", "inline")
    resolved_storage_root = Path(storage_root or os.getenv("STORAGE_ROOT", "./storage"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if resolved_database.startswith("sqlite"):
            os.makedirs("data", exist_ok=True)
        app.state.session_factory = build_session_factory(resolved_database)
        app.state.database_url = resolved_database
        app.state.task_mode = resolved_task_mode
        app.state.storage_root = resolved_storage_root
        app.state.object_store = LocalObjectStore(resolved_storage_root)
        app.state.task_queue = task_queue
        if resolved_task_mode == "rq" and app.state.task_queue is None:
            redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            app.state.task_queue = Queue("edusci", connection=redis)
        app.state.model_provider = resolved_provider
        app.state.retriever = (
            OpenResearchRetriever()
            if os.getenv("ENABLE_LIVE_RETRIEVAL", "false").lower() == "true"
            else None
        )
        yield

    app = FastAPI(
        title="教育智研 API",
        version="0.1.0",
        description="面向教育学实证研究的一体化 AI Scientist MVP",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "edusci-api"}

    app.include_router(router)
    return app


app = create_app()

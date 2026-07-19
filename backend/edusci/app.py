from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from rq import Queue
from sqlalchemy import text

from edusci.api.routes import router
from edusci.analysis.storage import LocalObjectStore
from edusci.integrations.qwen import QwenProvider
from edusci.integrations.datasets import default_dataset_adapters
from edusci.integrations.retrieval import (
    CrossrefLiteratureAdapter,
    OpenAccessFullTextFetcher,
    OpenResearchRetriever,
    SemanticScholarLiteratureAdapter,
)
from edusci.memory.database import build_session_factory


def create_app(
    database_url: str | None = None,
    task_mode: str | None = None,
    storage_root: str | Path | None = None,
    model_provider=None,
    task_queue=None,
    literature_adapters=None,
    dataset_adapters=None,
    fulltext_fetcher=None,
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
            generation_model=os.getenv("QWEN_GENERATION_MODEL", "qwen3.7-plus"),
            review_model=os.getenv("QWEN_REVIEW_MODEL", "qwen3.7-max"),
            embedding_model=os.getenv(
                "QWEN_EMBEDDING_MODEL", "text-embedding-v4"
            ),
            embedding_dimension=int(os.getenv("QWEN_EMBEDDING_DIMENSION", "1024")),
        )

    resolved_task_mode = task_mode or os.getenv("TASK_MODE", "inline")
    resolved_storage_root = Path(storage_root or os.getenv("STORAGE_ROOT", "./storage"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if resolved_database.startswith("sqlite"):
            os.makedirs("data", exist_ok=True)
        app.state.session_factory = build_session_factory(resolved_database)
        app.state.database_engine = app.state.session_factory.kw["bind"]
        app.state.database_url = resolved_database
        app.state.task_mode = resolved_task_mode
        app.state.storage_root = resolved_storage_root
        app.state.object_store = LocalObjectStore(resolved_storage_root)
        app.state.task_queue = task_queue
        if resolved_task_mode == "rq" and app.state.task_queue is None:
            redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            app.state.task_queue = Queue("edusci", connection=redis)
        app.state.model_provider = resolved_provider
        app.state.autonomous_enabled = (
            os.getenv("AUTONOMOUS_RESEARCH_ENABLED", "true").lower() == "true"
        )
        app.state.autonomous_max_literature_rounds = int(
            os.getenv("AUTONOMOUS_MAX_LITERATURE_ROUNDS", "3")
        )
        app.state.autonomous_max_results_per_query = int(
            os.getenv("AUTONOMOUS_MAX_RESULTS_PER_QUERY", "10")
        )
        app.state.deep_research_defaults = {
            "initial_rounds": int(os.getenv("AUTONOMOUS_INITIAL_ROUNDS", "5")),
            "max_rounds": int(os.getenv("AUTONOMOUS_MAX_ROUNDS", "10")),
            "initial_fulltexts": int(os.getenv("AUTONOMOUS_INITIAL_FULLTEXTS", "20")),
            "max_fulltexts": int(os.getenv("AUTONOMOUS_MAX_FULLTEXTS", "60")),
            "soft_timeout_minutes": int(
                os.getenv("AUTONOMOUS_SOFT_TIMEOUT_MINUTES", "60")
            ),
            "hard_timeout_minutes": int(
                os.getenv("AUTONOMOUS_HARD_TIMEOUT_MINUTES", "120")
            ),
        }
        download_limit = int(os.getenv("AUTONOMOUS_DOWNLOAD_LIMIT_MB", "50"))
        shared_client = None
        if literature_adapters is None or dataset_adapters is None:
            shared_client = httpx.Client(
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "EduSci-MVP/0.2"},
            )
        semantic_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        semantic_adapter = None
        if literature_adapters is None:
            semantic_adapter = SemanticScholarLiteratureAdapter(
                None if semantic_key else shared_client,
                api_key=semantic_key or None,
            )
            app.state.literature_adapters = [
                CrossrefLiteratureAdapter(shared_client),
                semantic_adapter,
            ]
        else:
            app.state.literature_adapters = literature_adapters
        app.state.dataset_adapters = dataset_adapters or default_dataset_adapters(
            shared_client
        )
        fulltext_client = None
        if fulltext_fetcher is None:
            fulltext_client = shared_client or httpx.Client(
                timeout=60,
                follow_redirects=True,
                headers={"User-Agent": "EduSci-MVP/0.3"},
            )
            app.state.fulltext_fetcher = OpenAccessFullTextFetcher(
                fulltext_client,
                max_size_bytes=download_limit * 1024 * 1024,
            )
        else:
            app.state.fulltext_fetcher = fulltext_fetcher
        for adapter in app.state.dataset_adapters:
            if hasattr(adapter, "max_size_bytes"):
                adapter.max_size_bytes = download_limit * 1024 * 1024
        app.state.retriever = (
            OpenResearchRetriever()
            if os.getenv("ENABLE_LIVE_RETRIEVAL", "false").lower() == "true"
            else None
        )
        try:
            yield
        finally:
            if shared_client is not None:
                shared_client.close()
            if semantic_adapter is not None and semantic_adapter.client is not shared_client:
                semantic_adapter.client.close()
            if fulltext_client is not None and fulltext_client is not shared_client:
                fulltext_client.close()
            app.state.database_engine.dispose()

    app = FastAPI(
        title="教育智研 API",
        version="0.1.0",
        description="面向教育学实证研究的一体化 AI Scientist MVP",
        lifespan=lifespan,
    )
    web_port = os.getenv("WEB_PORT", "5174")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{web_port}",
            f"http://127.0.0.1:{web_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "edusci-api"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        try:
            with app.state.database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "database": "unavailable"},
            ) from exc
        return {
            "status": "ready",
            "database": "ok",
            "model_provider": "configured" if resolved_provider is not None else "fallback",
            "task_mode": resolved_task_mode,
        }

    app.include_router(router)
    return app


app = create_app()

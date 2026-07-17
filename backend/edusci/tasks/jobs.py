from __future__ import annotations

import os
from pathlib import Path

import httpx
from sqlalchemy import select

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import SourceInput
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.deep_research import DeepResearchEngine
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.integrations.datasets import default_dataset_adapters
from edusci.integrations.qwen import QwenProvider
from edusci.integrations.retrieval import (
    CrossrefLiteratureAdapter,
    OpenAccessFullTextFetcher,
    OpenResearchRetriever,
    SemanticScholarLiteratureAdapter,
)
from edusci.memory.database import managed_session
from edusci.memory.models import AutonomousRunRecord, DatasetRecord, Project, TaskRecord
from edusci.services.analysis import run_analysis
from edusci.services.projects import run_evidence_build, run_gate, run_idea_parse
from edusci.services.reporting import run_report, run_review
from edusci.services.study import run_study_design


def _provider():
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return QwenProvider(
        api_key=api_key,
        base_url=os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        generation_model=os.getenv("QWEN_GENERATION_MODEL", "qwen3.7-plus"),
        review_model=os.getenv("QWEN_REVIEW_MODEL", "qwen3.7-max"),
    )


def default_literature_adapters() -> list:
    return [CrossrefLiteratureAdapter(), SemanticScholarLiteratureAdapter()]


def execute_autonomous_run(
    run_id: str,
    database_url: str,
    storage_root: str,
    action: str = "start",
    dataset_id: str | None = None,
) -> None:
    with managed_session(database_url) as session:
        store = LocalObjectStore(Path(storage_root))
        run = session.get(AutonomousRunRecord, run_id)
        if run is None:
            raise ValueError("自治研究任务不存在")
        config = run.config or {}
        dataset_adapters = default_dataset_adapters()
        literature_adapters = default_literature_adapters()
        provider = _provider()
        download_limit = int(os.getenv("AUTONOMOUS_DOWNLOAD_LIMIT_MB", "50"))
        for adapter in dataset_adapters:
            if hasattr(adapter, "max_size_bytes"):
                adapter.max_size_bytes = download_limit * 1024 * 1024
        fulltext_client = httpx.Client(
            timeout=60,
            follow_redirects=True,
            headers={"User-Agent": "EduSci-MVP/0.3"},
        )

        def deep_search(queries: list[str], iteration: int) -> list[dict]:
            del iteration
            results: list[dict] = []
            limit = int(config.get("max_results_per_query", 10))
            for adapter in literature_adapters:
                for query in queries:
                    try:
                        items = adapter.search(query, limit)
                    except Exception:
                        continue
                    results.extend(
                        {**item, "source": getattr(adapter, "name", "literature")}
                        for item in items
                    )
            return results

        deep_engine = None
        if provider is not None:
            fetcher = OpenAccessFullTextFetcher(
                fulltext_client,
                max_size_bytes=download_limit * 1024 * 1024,
            )
            deep_engine = DeepResearchEngine(
                session=session,
                provider=provider,
                search=deep_search,
                fetch_fulltext=fetcher.fetch,
            )
        orchestrator = AutonomousOrchestrator(
            session=session,
            store=store,
            planner=ResearchPlanner(provider),
            literature_scout=LiteratureScout(
                literature_adapters,
                max_rounds=int(
                    config.get(
                        "max_literature_rounds",
                        os.getenv("AUTONOMOUS_MAX_LITERATURE_ROUNDS", "3"),
                    )
                ),
                max_results_per_query=int(
                    config.get(
                        "max_results_per_query",
                        os.getenv("AUTONOMOUS_MAX_RESULTS_PER_QUERY", "10"),
                    )
                ),
            ),
            data_scout=DataScout(dataset_adapters, store),
            deep_research_engine=deep_engine,
        )
        try:
            if action == "start":
                orchestrator.start_existing(run_id)
            elif action == "real_data":
                if not dataset_id:
                    raise ValueError("真实数据恢复任务缺少 dataset_id")
                orchestrator.resume_after_real_data(run_id, dataset_id)
            else:
                orchestrator.resume(run_id)
        finally:
            fulltext_client.close()


def execute_task(task_id: str, database_url: str, storage_root: str) -> None:
    with managed_session(database_url) as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.status == "canceled":
            return
        project = session.get(Project, task.project_id)
        if project is None:
            raise ValueError("异步任务所属项目不存在")
        payload = task.input_payload or {}
        provider = _provider()

        if task.kind == "idea_parse":
            run_idea_parse(session, project, provider, task)
        elif task.kind == "evidence_build":
            sources = [SourceInput.model_validate(item) for item in payload.get("sources", [])]
            retriever = (
                OpenResearchRetriever()
                if os.getenv("ENABLE_LIVE_RETRIEVAL", "false").lower() == "true"
                else None
            )
            run_evidence_build(session, project, sources, retriever, task)
        elif task.kind == "gate":
            run_gate(session, project, task)
        elif task.kind == "study_design":
            run_study_design(session, project, task)
        elif task.kind == "analysis":
            dataset_id = payload.get("dataset_id")
            if not dataset_id:
                dataset = session.scalar(
                    select(DatasetRecord)
                    .where(DatasetRecord.project_id == project.id)
                    .order_by(DatasetRecord.created_at.desc())
                )
                dataset_id = dataset.id if dataset else None
            if not dataset_id:
                raise ValueError("分析任务缺少数据集")
            run_analysis(
                session,
                LocalObjectStore(Path(storage_root)),
                project,
                dataset_id,
                payload.get("outcome_column"),
                payload.get("group_column"),
                task,
            )
        elif task.kind == "report":
            run_report(session, project, task)
        elif task.kind == "review":
            run_review(session, project, provider, task)
        else:
            raise ValueError(f"未知任务类型: {task.kind}")

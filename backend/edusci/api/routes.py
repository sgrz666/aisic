from __future__ import annotations

from collections.abc import Generator

import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.api.schemas import (
    AutonomousRunCreate,
    AutonomousRunRef,
    AutonomousRunView,
    DatasetCandidateView,
    EvidenceCardView,
    EvidenceRunRequest,
    AnalysisRunRequest,
    DatasetView,
    ProjectCreate,
    ProjectSnapshot,
    RouteConfirmation,
    TaskRef,
    TaskView,
    DocumentView,
    FeedbackSignalCreate,
    FeedbackSignalView,
)
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.models import (
    AutonomousRunRecord,
    DatasetCandidateRecord,
    DatasetRecord,
    EvidenceCard,
    FeedbackSignal,
    FlowEvent,
    Project,
    TaskRecord,
)
from edusci.reporting.docx import build_report_docx
from edusci.services.analysis import run_analysis, save_dataset
from edusci.services.autonomy import (
    create_autonomous_run,
    request_cancellation,
    require_autonomous_run,
)
from edusci.services.projects import (
    confirm_route,
    create_project,
    require_project,
    run_evidence_build,
    run_gate,
    run_idea_parse,
    snapshot,
)
from edusci.services.study import run_study_design
from edusci.services.reporting import run_report, run_review
from edusci.services.documents import ingest_pdf
from edusci.tasks.dispatcher import enqueue_autonomous_run, enqueue_task

router = APIRouter(prefix="/api/v1")


def get_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def submit_task(
    request: Request,
    session: Session,
    project: Project,
    kind: str,
    payload: dict,
    inline,
) -> TaskRecord:
    if request.app.state.task_mode == "rq":
        return enqueue_task(
            session,
            request.app.state.task_queue,
            request.app.state.database_url,
            request.app.state.storage_root,
            project,
            kind,
            payload,
        )
    return inline()


def autonomous_orchestrator(
    request: Request, session: Session, config: dict | None = None
) -> AutonomousOrchestrator:
    store = request.app.state.object_store
    resolved_config = config or {}
    return AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(request.app.state.model_provider),
        literature_scout=LiteratureScout(
            request.app.state.literature_adapters,
            max_rounds=int(
                resolved_config.get(
                    "max_literature_rounds",
                    request.app.state.autonomous_max_literature_rounds,
                )
            ),
            max_results_per_query=int(
                resolved_config.get(
                    "max_results_per_query",
                    request.app.state.autonomous_max_results_per_query,
                )
            ),
        ),
        data_scout=DataScout(request.app.state.dataset_adapters, store),
    )


@router.post("/projects", response_model=ProjectSnapshot, status_code=status.HTTP_201_CREATED)
def projects_create(payload: ProjectCreate, session: Session = Depends(get_session)) -> dict:
    return snapshot(create_project(session, payload))


@router.get("/projects", response_model=list[ProjectSnapshot])
def projects_list(session: Session = Depends(get_session)) -> list[dict]:
    return [snapshot(project) for project in session.scalars(select(Project).order_by(Project.created_at.desc()))]


@router.get("/projects/{project_id}", response_model=ProjectSnapshot)
def projects_get(project_id: str, session: Session = Depends(get_session)) -> dict:
    return snapshot(require_project(session, project_id))


@router.post(
    "/projects/{project_id}/autonomous-runs",
    response_model=AutonomousRunRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def autonomous_run_start(
    project_id: str,
    payload: AutonomousRunCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    project = require_project(session, project_id)
    if not request.app.state.autonomous_enabled:
        raise HTTPException(status_code=404, detail="自治研究功能未启用")
    config = payload.model_dump()
    if request.app.state.task_mode == "rq":
        run = create_autonomous_run(session, project, config, queued=True)
        run = enqueue_autonomous_run(
            session,
            request.app.state.task_queue,
            request.app.state.database_url,
            request.app.state.storage_root,
            run,
            action="start",
        )
    else:
        run = autonomous_orchestrator(request, session, config).start(project, config)
    return {"task_id": run.task_id, "run_id": run.id, "status": run.status}


@router.get("/autonomous-runs/{run_id}", response_model=AutonomousRunView)
def autonomous_run_get(
    run_id: str, session: Session = Depends(get_session)
) -> AutonomousRunRecord:
    return require_autonomous_run(session, run_id)


@router.get("/autonomous-runs/{run_id}/events")
def autonomous_run_events(
    run_id: str, session: Session = Depends(get_session)
) -> StreamingResponse:
    run = require_autonomous_run(session, run_id)
    events = []
    if run.task_id:
        events = list(
            session.scalars(
                select(FlowEvent)
                .where(FlowEvent.task_id == run.task_id)
                .order_by(FlowEvent.id)
            )
        )

    def stream():
        for event in events:
            yield (
                f"event: {event.event_type}\n"
                f"data: {json.dumps(event.payload, ensure_ascii=False)}\n\n"
            )
        terminal_payload = {
            "run_id": run.id,
            "node": run.current_node,
            "status": run.status,
            "pause_reason": run.pause_reason,
        }
        yield (
            f"event: {run.status}\n"
            f"data: {json.dumps(terminal_payload, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/autonomous-runs/{run_id}/cancel", response_model=AutonomousRunRef)
def autonomous_run_cancel(
    run_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    run = request_cancellation(session, require_autonomous_run(session, run_id))
    if request.app.state.task_mode != "rq":
        run = autonomous_orchestrator(request, session, run.config).resume(run.id)
    return {"task_id": run.task_id, "run_id": run.id, "status": run.status}


@router.post(
    "/autonomous-runs/{run_id}/resume",
    response_model=AutonomousRunRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def autonomous_run_resume(
    run_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    run = require_autonomous_run(session, run_id)
    if run.status == "canceled":
        run.cancel_requested = False
        session.add(run)
        session.commit()
    if request.app.state.task_mode == "rq":
        run = enqueue_autonomous_run(
            session,
            request.app.state.task_queue,
            request.app.state.database_url,
            request.app.state.storage_root,
            run,
            action="resume",
        )
    else:
        run = autonomous_orchestrator(request, session, run.config).resume(run.id)
    return {"task_id": run.task_id, "run_id": run.id, "status": run.status}


@router.get(
    "/autonomous-runs/{run_id}/dataset-candidates",
    response_model=list[DatasetCandidateView],
)
def autonomous_dataset_candidates(
    run_id: str, session: Session = Depends(get_session)
) -> list[DatasetCandidateRecord]:
    require_autonomous_run(session, run_id)
    return list(
        session.scalars(
            select(DatasetCandidateRecord)
            .where(DatasetCandidateRecord.run_id == run_id)
            .order_by(
                DatasetCandidateRecord.selected.desc(),
                DatasetCandidateRecord.score.desc(),
            )
        )
    )


@router.post(
    "/projects/{project_id}/idea-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def idea_run(
    project_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request,
        session,
        project,
        "idea_parse",
        {},
        lambda: run_idea_parse(session, project, request.app.state.model_provider),
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.post(
    "/projects/{project_id}/evidence-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def evidence_run(
    project_id: str,
    payload: EvidenceRunRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request,
        session,
        project,
        "evidence_build",
        {"sources": [source.model_dump() for source in payload.sources]},
        lambda: run_evidence_build(
            session, project, payload.sources, request.app.state.retriever
        ),
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.get("/projects/{project_id}/evidence", response_model=list[EvidenceCardView])
def evidence_list(project_id: str, session: Session = Depends(get_session)) -> list[EvidenceCard]:
    require_project(session, project_id)
    return list(
        session.scalars(
            select(EvidenceCard)
            .where(EvidenceCard.project_id == project_id)
            .order_by(EvidenceCard.created_at)
        )
    )


@router.post(
    "/projects/{project_id}/gate-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def gate_run(
    project_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request, session, project, "gate", {}, lambda: run_gate(session, project)
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.post("/projects/{project_id}/route-confirmations", response_model=ProjectSnapshot)
def route_confirm(
    project_id: str, payload: RouteConfirmation, session: Session = Depends(get_session)
) -> dict:
    return snapshot(confirm_route(session, require_project(session, project_id), payload.route))


@router.post(
    "/projects/{project_id}/study-design-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def study_design_run(
    project_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request,
        session,
        project,
        "study_design",
        {},
        lambda: run_study_design(session, project),
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DatasetView,
    status_code=status.HTTP_201_CREATED,
)
async def dataset_upload(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    content = await file.read()
    project = require_project(session, project_id)
    dataset = save_dataset(
        session,
        request.app.state.object_store,
        project,
        file.filename or "dataset.csv",
        file.content_type or "application/octet-stream",
        content,
    )
    active_run = session.scalar(
        select(AutonomousRunRecord)
        .where(
            AutonomousRunRecord.project_id == project_id,
            AutonomousRunRecord.status == "awaiting_real_data",
        )
        .order_by(AutonomousRunRecord.created_at.desc())
    )
    if active_run is not None:
        if request.app.state.task_mode == "rq":
            enqueue_autonomous_run(
                session,
                request.app.state.task_queue,
                request.app.state.database_url,
                request.app.state.storage_root,
                active_run,
                action="real_data",
                dataset_id=dataset.id,
            )
        else:
            autonomous_orchestrator(request, session, active_run.config).resume_after_real_data(
                active_run.id, dataset.id
            )
    return dataset


@router.post(
    "/projects/{project_id}/analysis-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def analysis_run(
    project_id: str,
    payload: AnalysisRunRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request,
        session,
        project,
        "analysis",
        payload.model_dump(),
        lambda: run_analysis(
            session,
            request.app.state.object_store,
            project,
            payload.dataset_id,
            payload.outcome_column,
            payload.group_column,
        ),
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.post(
    "/projects/{project_id}/report-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def report_run(
    project_id: str, request: Request, session: Session = Depends(get_session)
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request, session, project, "report", {}, lambda: run_report(session, project)
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.post(
    "/projects/{project_id}/review-runs",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def review_run(
    project_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    project = require_project(session, project_id)
    task = submit_task(
        request,
        session,
        project,
        "review",
        {},
        lambda: run_review(session, project, request.app.state.model_provider),
    )
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.get("/projects/{project_id}/report.docx")
def report_download(
    project_id: str, mode: str = "final", session: Session = Depends(get_session)
) -> Response:
    project = require_project(session, project_id)
    if not project.report:
        raise HTTPException(status_code=404, detail="研究计划尚未生成")
    if mode not in {"draft", "final"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 draft 或 final")
    if mode == "final" and project.review.get("overall") == "BLOCK":
        raise HTTPException(status_code=409, detail="存在阻断风险，只能导出草稿版")
    content = build_report_docx(project.report, project.review, mode)
    disposition = f'attachment; filename="edusci-{project.id[:8]}-{mode}.docx"'
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition},
    )


@router.get("/tasks/{task_id}", response_model=TaskView)
def task_get(task_id: str, session: Session = Depends(get_session)) -> TaskRecord:
    task = session.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskView)
def task_cancel(task_id: str, session: Session = Depends(get_session)) -> TaskRecord:
    task = session.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {"queued", "started"}:
        raise HTTPException(status_code=409, detail="仅排队中或运行中的任务可以取消")
    task.status = "canceled"
    task.retryable = True
    session.add(
        FlowEvent(task_id=task.id, event_type="failed", payload={"code": "USER_CANCELED"})
    )
    session.commit()
    session.refresh(task)
    return task


@router.post(
    "/tasks/{task_id}/retry",
    response_model=TaskRef,
    status_code=status.HTTP_202_ACCEPTED,
)
def task_retry(
    task_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    previous = session.get(TaskRecord, task_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if previous.status not in {"failed", "canceled"} or not previous.retryable:
        raise HTTPException(status_code=409, detail="该任务当前不可重试")
    if previous.project_id is None:
        raise HTTPException(status_code=409, detail="任务缺少所属项目")
    project = require_project(session, previous.project_id)

    if request.app.state.task_mode == "rq":
        task = enqueue_task(
            session,
            request.app.state.task_queue,
            request.app.state.database_url,
            request.app.state.storage_root,
            project,
            previous.kind,
            previous.input_payload,
        )
        previous.retryable = False
        previous.error = {**(previous.error or {}), "retried_by": task.id}
        session.add(previous)
        session.commit()
        return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}

    if previous.kind == "idea_parse":
        task = run_idea_parse(session, project, request.app.state.model_provider)
    elif previous.kind == "evidence_build":
        task = run_evidence_build(session, project, [], request.app.state.retriever)
    elif previous.kind == "gate":
        task = run_gate(session, project)
    elif previous.kind == "study_design":
        task = run_study_design(session, project)
    elif previous.kind == "analysis":
        dataset = session.scalar(
            select(DatasetRecord)
            .where(DatasetRecord.project_id == project.id)
            .order_by(DatasetRecord.created_at.desc())
        )
        if dataset is None:
            raise HTTPException(status_code=409, detail="分析节点重试前需要重新上传数据集")
        task = run_analysis(
            session, request.app.state.object_store, project, dataset.id, None, None
        )
    elif previous.kind == "report":
        task = run_report(session, project)
    elif previous.kind == "review":
        task = run_review(session, project, request.app.state.model_provider)
    else:
        raise HTTPException(status_code=409, detail="该节点暂不支持原位重试")

    previous.retryable = False
    previous.error = {**(previous.error or {}), "retried_by": task.id}
    session.add(previous)
    session.commit()
    return {"task_id": task.id, "status": task.status, "resource_id": task.resource_id}


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, session: Session = Depends(get_session)) -> StreamingResponse:
    task = session.get(TaskRecord, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = list(
        session.scalars(
            select(FlowEvent).where(FlowEvent.task_id == task_id).order_by(FlowEvent.id)
        )
    )

    def stream():
        for event in events:
            yield f"event: {event.event_type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentView,
    status_code=status.HTTP_201_CREATED,
)
async def document_upload(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    return ingest_pdf(
        session,
        request.app.state.object_store,
        require_project(session, project_id),
        file.filename or "document.pdf",
        await file.read(),
    )


@router.post(
    "/projects/{project_id}/feedback-signals",
    response_model=FeedbackSignalView,
    status_code=status.HTTP_201_CREATED,
)
def feedback_signal_create(
    project_id: str,
    payload: FeedbackSignalCreate,
    session: Session = Depends(get_session),
) -> FeedbackSignal:
    require_project(session, project_id)
    signal = FeedbackSignal(
        project_id=project_id,
        **payload.model_dump(),
        proposal={
            "dimension": "workflow",
            "action": "review_only",
            "reason": "MVP 仅记录改进提案，不自动修改 Prompt 或 DAG",
        },
    )
    session.add(signal)
    session.commit()
    session.refresh(signal)
    return signal

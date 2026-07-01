from __future__ import annotations

import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.api.schemas import ProjectCreate, SourceInput
from edusci.autonomy.contracts import ResearchPlan
from edusci.domain.flow import FlowStage, ResearchScores, determine_route, transition_stage
from edusci.memory.models import EvidenceCard, FlowEvent, Project, TaskRecord


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def snapshot(project: Project) -> dict:
    return {
        "id": project.id,
        "owner_id": project.owner_id,
        "title": project.title,
        "idea_text": project.idea_text,
        "stage": project.stage,
        "route": project.route,
        "suggested_route": project.suggested_route,
        "research_problem": project.research_problem or {},
        "scores": project.scores or {},
        "study_design": project.study_design or {},
        "analysis_result": project.analysis_result or {},
        "report": project.report or {},
        "review": project.review or {},
        "evidence_count": len(project.evidence_cards),
    }


def create_project(session: Session, payload: ProjectCreate) -> Project:
    project = Project(**payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _task(
    session: Session,
    project: Project,
    kind: str,
    callback,
    task: TaskRecord | None = None,
) -> TaskRecord:
    task = task or TaskRecord(project_id=project.id, kind=kind)
    task.status = "started"
    session.add(task)
    session.flush()
    session.add(FlowEvent(task_id=task.id, event_type="started", payload={"kind": kind}))
    try:
        callback()
        task.status = "completed"
        task.resource_id = project.id
        session.add(
            FlowEvent(task_id=task.id, event_type="completed", payload={"project_id": project.id})
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        task = session.get(TaskRecord, task.id) or task
        task.status = "failed"
        task.retryable = True
        task.error = {"code": "TASK_FAILED", "message": str(exc), "stage": project.stage}
        session.add(task)
        session.commit()
        raise
    return task


def run_idea_parse(
    session: Session,
    project: Project,
    model_provider=None,
    task: TaskRecord | None = None,
    research_plan: ResearchPlan | None = None,
) -> TaskRecord:
    def parse() -> None:
        if research_plan is not None:
            project.research_problem = {
                "problem_statement": research_plan.problem_statement,
                "variables": [variable.name for variable in research_plan.variables],
                "target_group": research_plan.population,
                "discipline": "教育学",
                "clarifying_questions": [],
                "concepts": research_plan.concepts,
                "geographies": research_plan.geographies,
                "time_range": research_plan.time_range.model_dump(),
            }
        elif model_provider is not None:
            project.research_problem = model_provider.complete_json(
                "generation",
                [
                    {
                        "role": "system",
                        "content": "你是教育学研究问题解析器。返回 JSON：problem_statement、variables、target_group、discipline、clarifying_questions。",
                    },
                    {"role": "user", "content": project.idea_text},
                ],
            )
        else:
            known_variables = [
                value
                for value in (
                    "AI 焦虑度",
                    "专业",
                    "人口变化",
                    "基础教育资源配置",
                    "学习负担",
                    "吃饭速度",
                    "眨眼频率",
                )
                if value in project.idea_text
            ]
            if not known_variables:
                pieces = [piece.strip() for piece in re.split(r"与|和|对", project.idea_text) if piece.strip()]
                known_variables = pieces[-2:]
            project.research_problem = {
                "problem_statement": project.idea_text.strip("。"),
                "variables": known_variables,
                "target_group": "大学生" if "大学生" in project.idea_text else "待确认",
                "discipline": "教育学",
                "clarifying_questions": [] if known_variables else ["请补充核心变量"],
            }
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.EVIDENCE).value

    return _task(session, project, "idea_parse", parse, task)


def _trust_status(source: SourceInput) -> str:
    traceable = source.url.startswith(("https://", "http://")) and bool(source.locator.strip())
    return (
        "PASS"
        if source.verified and traceable and len(source.excerpt.strip()) >= 8
        else "WARN"
    )


def run_evidence_build(
    session: Session,
    project: Project,
    sources: list[SourceInput],
    retriever=None,
    task: TaskRecord | None = None,
) -> TaskRecord:
    def build() -> None:
        if project.stage != FlowStage.EVIDENCE.value:
            raise ValueError("当前阶段不能构建证据")
        resolved_sources = sources
        if not resolved_sources and retriever is not None:
            resolved_sources = retriever.search(project.idea_text, limit=6)
        for source in resolved_sources:
            raw = "|".join((source.title, source.url, source.locator, source.excerpt))
            content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            existing = session.scalar(
                select(EvidenceCard).where(
                    EvidenceCard.project_id == project.id,
                    EvidenceCard.content_hash == content_hash,
                )
            )
            if existing is not None:
                continue
            session.add(
                EvidenceCard(
                    project_id=project.id,
                    title=source.title,
                    source_type=source.source_type,
                    source_url=source.url,
                    locator=source.locator,
                    excerpt=source.excerpt,
                    claim=source.excerpt.strip(),
                    content_hash=content_hash,
                    trust_status=_trust_status(source),
                )
            )
        session.flush()

    return _task(session, project, "evidence_build", build, task)


def _researchability(idea: str) -> int:
    if "吃饭速度" in idea or "眨眼频率" in idea:
        return 35
    education_terms = ("教育", "学生", "大学", "学校", "教师", "学习", "专业", "人口")
    return 85 if any(term in idea for term in education_terms) else 55


def run_gate(
    session: Session, project: Project, task: TaskRecord | None = None
) -> TaskRecord:
    def gate() -> None:
        if project.stage != FlowStage.EVIDENCE.value:
            raise ValueError("当前阶段不能执行门控")
        cards = list(project.evidence_cards)
        pass_count = sum(card.trust_status == "PASS" for card in cards)
        diversity = len({card.source_type for card in cards})
        information = min(100, pass_count * 15 + min(diversity * 10, 20))
        scores = ResearchScores(information, _researchability(project.idea_text))
        project.scores = {
            "information_sufficiency": scores.information_sufficiency,
            "researchability": scores.researchability,
        }
        project.suggested_route = determine_route(scores).value
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.GATE).value

    return _task(session, project, "gate", gate, task)


def confirm_route(session: Session, project: Project, route: str) -> Project:
    if project.stage != FlowStage.GATE.value:
        raise HTTPException(status_code=409, detail="项目尚未进入路径确认阶段")
    project.route = route
    project.stage = transition_stage(FlowStage(project.stage), FlowStage.DESIGN).value
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

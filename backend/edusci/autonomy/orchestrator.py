from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import SourceInput
from edusci.autonomy.checkpoints import CheckpointStore
from edusci.autonomy.contracts import ResearchPlan
from edusci.autonomy.data_scout import DataScout, DataScoutResult
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.models import (
    AutonomousRunRecord,
    DatasetAssetRecord,
    DatasetCandidateRecord,
    Project,
    ProvenanceRecord,
    ResearchPlanRecord,
    SearchAttemptRecord,
    TaskRecord,
)
from edusci.services.autonomy import create_autonomous_run, require_autonomous_run
from edusci.services.projects import run_evidence_build, run_gate, run_idea_parse


class AutonomousOrchestrator:
    def __init__(
        self,
        *,
        session: Session,
        store: LocalObjectStore,
        planner: ResearchPlanner,
        literature_scout: LiteratureScout,
        data_scout: DataScout,
    ) -> None:
        self.session = session
        self.store = store
        self.planner = planner
        self.literature_scout = literature_scout
        self.data_scout = data_scout

    def start(self, project: Project, config: dict | None = None) -> AutonomousRunRecord:
        run = create_autonomous_run(self.session, project, config)
        return self._run_to_gate(run, project)

    def resume(self, run_id: str) -> AutonomousRunRecord:
        run = require_autonomous_run(self.session, run_id)
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError("自治研究关联的项目不存在")
        if run.cancel_requested:
            return self._cancel(run)
        if run.status == "awaiting_route_confirmation" and not project.route:
            return run
        if project.stage == "S2_GATE":
            return self._run_to_gate(run, project)
        return run

    def _run_to_gate(
        self, run: AutonomousRunRecord, project: Project
    ) -> AutonomousRunRecord:
        checkpoints = CheckpointStore(self.session, run)
        try:
            self._check_canceled(run)
            run.status = "planning"
            self.session.commit()
            plan_output = checkpoints.run_node(
                "planning",
                {"idea_text": project.idea_text},
                lambda: self._plan(run, project),
                progress=10,
                message="解析研究问题并生成检索计划",
            ).output
            plan = ResearchPlan.model_validate(plan_output)

            self._check_canceled(run)
            checkpoints.run_node(
                "idea_parse",
                {"project_id": project.id, "plan": plan_output},
                lambda: self._parse_idea(project, plan),
                progress=20,
                message="写入结构化研究问题",
            )

            self._check_canceled(run)
            run.status = "searching_literature"
            self.session.commit()
            literature_output = checkpoints.run_node(
                "literature",
                {
                    "queries": [query.model_dump() for query in plan.literature_queries],
                    "concepts": plan.concepts,
                },
                lambda: self._discover_literature(run, plan),
                progress=40,
                message="多轮检索并筛选可追溯文献",
            ).output

            self._check_canceled(run)
            run.status = "searching_datasets"
            self.session.commit()
            data_output = checkpoints.run_node(
                "data_discovery",
                {
                    "requirements": [
                        requirement.model_dump() for requirement in plan.data_requirements
                    ],
                    "geographies": plan.geographies,
                    "time_range": plan.time_range.model_dump(),
                },
                lambda: self._discover_data(run, project, plan),
                progress=60,
                message="检索、评分并验证官方开放数据",
            ).output
            data_result = DataScoutResult.model_validate(data_output)
            if data_result.status == "paused_risk":
                run.status = "paused_risk"
                run.pause_reason = data_result.risk_report
                self.session.add(run)
                self.session.commit()
                return run

            self._check_canceled(run)
            checkpoints.run_node(
                "evidence_persist",
                {"literature": literature_output},
                lambda: self._persist_evidence(project, literature_output),
                progress=75,
                message="构建并校验证据卡片",
            )

            self._check_canceled(run)
            has_usable_dataset = data_result.status == "selected"
            checkpoints.run_node(
                "gate",
                {
                    "project_id": project.id,
                    "has_usable_dataset": has_usable_dataset,
                    "evidence_count": len(project.evidence_cards),
                },
                lambda: self._gate(project, has_usable_dataset),
                progress=85,
                message="计算信息充足度与可研究性",
            )
            run.status = "awaiting_route_confirmation"
            run.current_node = "human_gate"
            run.pause_reason = {
                "kind": "route_confirmation",
                "suggested_route": project.suggested_route,
            }
            self.session.add(run)
            self.session.commit()
            return run
        except _Canceled:
            return self._cancel(run)
        except Exception as exc:
            self.session.rollback()
            run = require_autonomous_run(self.session, run.id)
            run.status = "failed"
            run.error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "node": run.current_node,
            }
            if run.task_id:
                task = self.session.get(TaskRecord, run.task_id)
                if task:
                    task.status = "failed"
                    task.retryable = True
                    task.error = run.error
            self.session.add(run)
            self.session.commit()
            raise

    def _plan(self, run: AutonomousRunRecord, project: Project) -> dict:
        plan = self.planner.plan(project.idea_text)
        existing = self.session.scalar(
            select(ResearchPlanRecord).where(ResearchPlanRecord.run_id == run.id)
        )
        if existing is None:
            self.session.add(
                ResearchPlanRecord(run_id=run.id, plan_json=plan.model_dump(mode="json"))
            )
            self.session.commit()
        return plan.model_dump(mode="json")

    def _parse_idea(self, project: Project, plan: ResearchPlan) -> dict:
        run_idea_parse(self.session, project, research_plan=plan)
        return {"research_problem": project.research_problem, "stage": project.stage}

    def _discover_literature(
        self, run: AutonomousRunRecord, plan: ResearchPlan
    ) -> dict:
        result = self.literature_scout.discover(
            plan.literature_queries, plan.concepts
        )
        for attempt in result.attempts:
            self.session.add(SearchAttemptRecord(run_id=run.id, **attempt.model_dump()))
        self.session.commit()
        return result.model_dump(mode="json")

    def _discover_data(
        self, run: AutonomousRunRecord, project: Project, plan: ResearchPlan
    ) -> dict:
        result = self.data_scout.discover_and_select(plan, project.id)
        records: dict[tuple[str, str], DatasetCandidateRecord] = {}
        for candidate in result.candidates:
            record = DatasetCandidateRecord(
                run_id=run.id,
                project_id=project.id,
                source=candidate.source,
                external_id=candidate.dataset_id,
                title=candidate.title,
                provenance_url=candidate.provenance_url,
                score=candidate.score,
                selected=(
                    result.selected is not None
                    and candidate.dataset_id == result.selected.dataset_id
                    and candidate.source == result.selected.source
                ),
                candidate_json=candidate.model_dump(mode="json"),
            )
            self.session.add(record)
            records[(candidate.source, candidate.dataset_id)] = record
        self.session.flush()
        if result.asset is not None and result.selected is not None:
            selected_record = records[(result.selected.source, result.selected.dataset_id)]
            asset = DatasetAssetRecord(
                run_id=run.id,
                project_id=project.id,
                candidate_id=selected_record.id,
                storage_path=result.asset.storage_path,
                content_hash=result.asset.content_hash,
                row_count=result.asset.row_count,
                column_count=result.asset.column_count,
                schema_json=result.asset.data_schema,
                quality_report=result.asset.quality_report,
            )
            self.session.add(asset)
            self.session.flush()
            if result.provenance is not None:
                self.session.add(
                    ProvenanceRecord(
                        run_id=run.id,
                        entity_type="dataset_asset",
                        entity_id=asset.id,
                        **result.provenance.model_dump(),
                    )
                )
        self.session.commit()
        return result.model_dump(mode="json")

    def _persist_evidence(self, project: Project, literature_output: dict) -> dict:
        sources = []
        for candidate in literature_output.get("candidates", []):
            if candidate.get("exclusion_reason"):
                continue
            locator = candidate.get("doi") or str(candidate.get("year") or "online")
            sources.append(
                SourceInput(
                    title=candidate["title"],
                    source_type="scholarly",
                    url=candidate["url"],
                    locator=locator,
                    excerpt=candidate["abstract"],
                    verified=True,
                )
            )
        run_evidence_build(self.session, project, sources)
        return {"evidence_count": len(project.evidence_cards)}

    def _gate(self, project: Project, has_usable_dataset: bool) -> dict:
        run_gate(self.session, project, has_usable_dataset=has_usable_dataset)
        return {
            "scores": project.scores,
            "suggested_route": project.suggested_route,
            "stage": project.stage,
        }

    @staticmethod
    def _check_canceled(run: AutonomousRunRecord) -> None:
        if run.cancel_requested:
            raise _Canceled

    def _cancel(self, run: AutonomousRunRecord) -> AutonomousRunRecord:
        run.status = "canceled"
        if run.task_id:
            task = self.session.get(TaskRecord, run.task_id)
            if task:
                task.status = "canceled"
        self.session.add(run)
        self.session.commit()
        return run


class _Canceled(Exception):
    pass

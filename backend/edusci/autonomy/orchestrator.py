from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import SourceInput
from edusci.autonomy.checkpoints import CheckpointStore
from edusci.autonomy.contracts import ResearchPlan
from edusci.autonomy.contracts import DeepResearchLimits
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
from edusci.services.analysis import promote_public_dataset, run_analysis
from edusci.services.projects import confirm_route, run_evidence_build, run_gate, run_idea_parse
from edusci.services.reporting import run_report, run_review
from edusci.services.study import run_study_design


class AutonomousOrchestrator:
    def __init__(
        self,
        *,
        session: Session,
        store: LocalObjectStore,
        planner: ResearchPlanner,
        literature_scout: LiteratureScout,
        data_scout: DataScout,
        deep_research_engine=None,
    ) -> None:
        self.session = session
        self.store = store
        self.planner = planner
        self.literature_scout = literature_scout
        self.data_scout = data_scout
        self.deep_research_engine = deep_research_engine

    def start(self, project: Project, config: dict | None = None) -> AutonomousRunRecord:
        run = create_autonomous_run(self.session, project, config)
        return self._run_to_gate(run, project)

    def start_existing(self, run_id: str) -> AutonomousRunRecord:
        run = require_autonomous_run(self.session, run_id)
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError("自治研究关联的项目不存在")
        if project.stage != "S0_IDEA":
            return self.resume(run_id)
        if run.task_id:
            task = self.session.get(TaskRecord, run.task_id)
            if task:
                task.status = "started"
        run.status = "planning"
        self.session.add(run)
        self.session.commit()
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
        if project.route and project.stage == "S3_DESIGN":
            return self._run_after_route(run, project)
        if project.stage == "S2_GATE":
            return self._run_to_gate(run, project)
        return run

    def resume_after_real_data(
        self, run_id: str, dataset_id: str
    ) -> AutonomousRunRecord:
        run = require_autonomous_run(self.session, run_id)
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise RuntimeError("自治研究关联的项目不存在")
        if run.status != "awaiting_real_data" or project.stage != "S4_ANALYSIS":
            raise ValueError("当前自治研究不在真实数据恢复阶段")
        return self._analyze_report_review(run, project, dataset_id, "uploaded")

    def _run_after_route(
        self, run: AutonomousRunRecord, project: Project
    ) -> AutonomousRunRecord:
        checkpoints = CheckpointStore(self.session, run)
        try:
            self._check_canceled(run)
            run.status = "designing_study"
            self.session.commit()
            checkpoints.run_node(
                "study_design",
                {
                    "project_id": project.id,
                    "route": project.route,
                    "research_problem": project.research_problem,
                },
                lambda: self._study_design(project),
                progress=90,
                message="生成与确认路径一致的研究设计",
            )

            if project.route == "B":
                run.status = "awaiting_real_data"
                run.current_node = "real_data_gate"
                run.pause_reason = {
                    "kind": "real_data_required",
                    "message": "问卷已生成，请上传真实回收数据后继续",
                }
                self.session.add(run)
                self.session.commit()
                return run

            if project.route == "A":
                asset = self.session.scalar(
                    select(DatasetAssetRecord).where(
                        DatasetAssetRecord.run_id == run.id
                    )
                )
                if asset is None:
                    raise ValueError("路径 A 缺少已验证的公开数据资产")
                dataset_output = checkpoints.run_node(
                    "prepare_public_dataset",
                    {"asset_id": asset.id, "content_hash": asset.content_hash},
                    lambda: self._promote_dataset(project, asset),
                    progress=92,
                    message="将已验证公开数据接入受控分析引擎",
                ).output
                return self._analyze_report_review(
                    run, project, dataset_output["dataset_id"], "official"
                )

            return self._report_review(run, project)
        except _Canceled:
            return self._cancel(run)
        except Exception as exc:
            self._fail(run, exc)
            raise

    def _analyze_report_review(
        self,
        run: AutonomousRunRecord,
        project: Project,
        dataset_id: str,
        dataset_origin: str,
    ) -> AutonomousRunRecord:
        checkpoints = CheckpointStore(self.session, run)
        try:
            self._check_canceled(run)
            run.status = "analyzing"
            self.session.commit()
            checkpoints.run_node(
                "analysis",
                {"dataset_id": dataset_id, "origin": dataset_origin},
                lambda: self._analysis(project, dataset_id),
                progress=94,
                message="使用白名单统计函数分析真实数据",
            )
            return self._report_review(run, project)
        except _Canceled:
            return self._cancel(run)
        except Exception as exc:
            self._fail(run, exc)
            raise

    def _report_review(
        self, run: AutonomousRunRecord, project: Project
    ) -> AutonomousRunRecord:
        checkpoints = CheckpointStore(self.session, run)
        try:
            self._check_canceled(run)
            run.status = "generating_report"
            self.session.commit()
            checkpoints.run_node(
                "report",
                {
                    "route": project.route,
                    "study_design": project.study_design,
                    "analysis_result": project.analysis_result,
                },
                lambda: self._report(project),
                progress=97,
                message="生成带引用来源链的研究报告",
            )
            self._check_canceled(run)
            run.status = "reviewing"
            self.session.commit()
            checkpoints.run_node(
                "review",
                {"route": project.route, "report": project.report},
                lambda: self._review(project),
                progress=100,
                message="执行引用、统计、逻辑与伦理复审",
            )
            run.status = "completed"
            run.current_node = "completed"
            run.pause_reason = {}
            if run.task_id:
                task = self.session.get(TaskRecord, run.task_id)
                if task:
                    task.status = "completed"
                    task.resource_id = project.id
            self.session.add(run)
            self.session.commit()
            return run
        except _Canceled:
            return self._cancel(run)
        except Exception as exc:
            self._fail(run, exc)
            raise

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

            if self.deep_research_engine is not None:
                self._check_canceled(run)
                run.status = "validating_evidence"
                self.session.commit()
                deep_output = checkpoints.run_node(
                    "deep_research",
                    {
                        "queries": [query.query for query in plan.literature_queries],
                        "limits": {
                            key: value
                            for key, value in run.config.items()
                            if key in DeepResearchLimits.model_fields
                        },
                    },
                    lambda: self._deep_research(run, project, plan),
                    progress=55,
                    message="解析开放全文并迭代补齐证据与反证",
                ).output
                self._apply_deep_metrics(run, deep_output)

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
            if not bool(run.config.get("require_route_confirmation", True)):
                confirm_route(
                    self.session,
                    project,
                    project.suggested_route or "D",
                )
                return self._run_after_route(run, project)
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

    def _deep_research(
        self, run: AutonomousRunRecord, project: Project, plan: ResearchPlan
    ) -> dict:
        limit_fields = set(DeepResearchLimits.model_fields)
        limits = DeepResearchLimits.model_validate(
            {key: value for key, value in run.config.items() if key in limit_fields}
        )
        result = self.deep_research_engine.run(
            run_id=run.id,
            project_id=project.id,
            seed_queries=[query.query for query in plan.literature_queries],
            subquestions=[plan.problem_statement, *plan.concepts],
            limits=limits,
        )
        return result.model_dump(mode="json")

    def _apply_deep_metrics(self, run: AutonomousRunRecord, output: dict) -> None:
        run.current_iteration = int(output.get("iterations") or 0)
        run.source_count = int(output.get("source_count") or 0)
        run.fulltext_count = int(output.get("fulltext_count") or 0)
        run.claim_count = int(output.get("claim_count") or 0)
        run.coverage = int(output.get("coverage") or 0)
        run.counter_evidence_coverage = int(
            output.get("counter_evidence_coverage") or 0
        )
        run.model_usage = dict(output.get("model_usage") or {})
        run.stop_reason = str(output.get("stop_reason") or "")
        run.degraded_sources = list(output.get("degraded_sources") or [])
        run.quality_metrics = dict(output.get("quality_metrics") or {})
        run.quality_gate_status = str(
            output.get("quality_gate_status") or "LIMITED"
        )
        self.session.add(run)
        self.session.commit()

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
                    bibliographic={
                        "authors": candidate.get("authors", []),
                        "year": candidate.get("year"),
                        "source_title": candidate.get("source_title", ""),
                        "volume": candidate.get("volume", ""),
                        "issue": candidate.get("issue", ""),
                        "pages": candidate.get("pages", ""),
                        "publisher": candidate.get("publisher", ""),
                        "doi": candidate.get("doi", ""),
                        "reference_type": candidate.get("reference_type", "J"),
                    },
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

    def _study_design(self, project: Project) -> dict:
        run_study_design(self.session, project)
        return {"study_design": project.study_design, "stage": project.stage}

    def _promote_dataset(
        self, project: Project, asset: DatasetAssetRecord
    ) -> dict:
        dataset = promote_public_dataset(self.session, project, asset)
        return {"dataset_id": dataset.id}

    def _analysis(self, project: Project, dataset_id: str) -> dict:
        run_analysis(
            self.session,
            self.store,
            project,
            dataset_id,
            outcome_column=None,
            group_column=None,
        )
        return {"analysis_result": project.analysis_result, "stage": project.stage}

    def _report(self, project: Project) -> dict:
        run_report(self.session, project)
        return {"report": project.report, "stage": project.stage}

    def _review(self, project: Project) -> dict:
        run_review(
            self.session,
            project,
            model_provider=self.planner.model_provider,
        )
        return {"review": project.review, "stage": project.stage}

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

    def _fail(self, run: AutonomousRunRecord, exc: Exception) -> None:
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


class _Canceled(Exception):
    pass

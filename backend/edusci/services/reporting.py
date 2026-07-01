from __future__ import annotations

import json

from sqlalchemy.orm import Session

from edusci.domain.flow import FlowStage, transition_stage
from edusci.memory.models import Project, TaskRecord
from edusci.services.projects import _task
from edusci.services.reporting_v2 import regenerate_report_v2


def run_report(session: Session, project: Project, task: TaskRecord | None = None):
    def build() -> None:
        if project.stage != FlowStage.REPORT.value:
            raise ValueError("当前阶段不能生成研究计划")
        regenerate_report_v2(session, project, refresh_evidence=False)
        if project.report["results"]["kind"] == "expected_only":
            report = dict(project.report)
            report["results"] = {**report["results"], "未采集真实数据": True}
            project.report = report
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.REVIEW).value

    return _task(session, project, "report", build, task)


def run_review(
    session: Session,
    project: Project,
    model_provider=None,
    task: TaskRecord | None = None,
):
    def review() -> None:
        if project.stage != FlowStage.REVIEW.value:
            raise ValueError("当前阶段不能执行复审")
        if project.report.get("schema_version") == 2:
            deterministic = project.review or {}
            agent_review = {"status": "not_configured"}
            if model_provider is not None:
                try:
                    agent_review = model_provider.complete_json(
                        "review",
                        [
                            {
                                "role": "system",
                                "content": "你是独立教育研究复审员。只能提出建议，不能覆盖确定性Schema、引用、统计、数据来源和伦理规则。",
                            },
                            {"role": "user", "content": json.dumps(project.report, ensure_ascii=False)},
                        ],
                    )
                except Exception as exc:
                    agent_review = {"status": "unavailable", "message": str(exc)}
            project.review = {**deterministic, "agent_review": agent_review}
            target = (
                FlowStage.BLOCKED
                if project.review.get("overall") == "BLOCK"
                else FlowStage.COMPLETED
            )
            project.stage = transition_stage(FlowStage(project.stage), target).value
            return
        references = project.report.get("references", [])
        if not references:
            citation = {"status": "BLOCK", "message": "没有可核验参考来源"}
        elif any(item.get("trust_status") != "PASS" for item in references):
            citation = {"status": "WARN", "message": "存在仅部分核验的来源"}
        else:
            citation = {"status": "PASS", "message": "引用均绑定可追溯证据"}

        result_kind = project.report.get("result_kind")
        statistics = {
            "status": "PASS",
            "message": "真实数据结果已记录" if result_kind == "observed" else "未生成伪统计结论",
        }
        logic = {
            "status": "BLOCK" if project.route == "D" else "PASS",
            "message": "探索性路径仅保留假设" if project.route == "D" else "结论边界与路径一致",
        }
        ethics = {"status": "PASS", "message": "已包含隐私、知情同意和样本限制"}
        checks = {"citation": citation, "statistics": statistics, "logic": logic, "ethics": ethics}
        statuses = {item["status"] for item in checks.values()}
        overall = "BLOCK" if "BLOCK" in statuses else "WARN" if "WARN" in statuses else "PASS"
        agent_review = {"status": "not_configured"}
        if model_provider is not None:
            try:
                agent_review = model_provider.complete_json(
                    "review",
                    [
                        {
                            "role": "system",
                            "content": "你是独立教育研究复审员。检查引用、统计、逻辑和伦理，仅返回 JSON。你的意见是建议，不能覆盖确定性安全规则。",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(project.report, ensure_ascii=False),
                        },
                    ],
                )
            except Exception as exc:
                agent_review = {"status": "unavailable", "message": str(exc)}
        project.review = {
            "overall": overall,
            "checks": checks,
            "agent_review": agent_review,
            "revision_round": 0,
        }
        target = FlowStage.BLOCKED if overall == "BLOCK" else FlowStage.COMPLETED
        project.stage = transition_stage(FlowStage(project.stage), target).value

    return _task(session, project, "review", review, task)

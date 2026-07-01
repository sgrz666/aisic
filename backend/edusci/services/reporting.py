from __future__ import annotations

import json

from sqlalchemy.orm import Session

from edusci.domain.flow import FlowStage, transition_stage
from edusci.memory.models import Project, TaskRecord
from edusci.services.projects import _task


def run_report(session: Session, project: Project, task: TaskRecord | None = None):
    def build() -> None:
        if project.stage != FlowStage.REPORT.value:
            raise ValueError("当前阶段不能生成研究计划")
        evidence = list(project.evidence_cards)
        verified_evidence = [card for card in evidence if card.trust_status == "PASS"]
        has_analysis = bool(project.analysis_result)
        variables = project.research_problem.get("variables", [])
        project.report = {
            "title": f"{project.title}：教育学科学假设与研究计划",
            "abstract": "本计划围绕用户提出的教育研究问题，整合可追溯证据并给出可验证研究路径。",
            "problem": project.research_problem.get("problem_statement", project.idea_text),
            "rationale": "依据现有证据识别变量关系、知识缺口与可证伪的后续研究方向。",
            "hypotheses": project.study_design.get("hypotheses", []),
            "variables": variables,
            "datasets": [project.analysis_result.get("dataset_id")] if has_analysis else [],
            "methods": "使用受控统计函数执行描述统计、差异检验与相关分析。"
            if has_analysis
            else "采用文献综合、变量操作化与后续数据采集方案。",
            "experiments": project.study_design.get("analysis_plan")
            or project.study_design.get("questionnaire")
            or project.study_design.get("synthesis_plan"),
            "results": "已对用户上传的真实数据执行受控统计分析，具体数值见分析结果。"
            if has_analysis
            else "尚未采集真实数据，本节仅陈述预期结果与验证标准，不包含统计结论。",
            "result_kind": "observed" if has_analysis else "expected_only",
            "limitations_ethics": "结论受样本、测量和研究设计限制；涉及学生数据时必须脱敏并取得知情同意。",
            "references": [
                {
                    "evidence_id": card.id,
                    "title": card.title,
                    "url": card.source_url,
                    "locator": card.locator,
                    "trust_status": card.trust_status,
                }
                for card in verified_evidence
            ],
            "citation_map": [
                {"claim": card.claim, "evidence_id": card.id, "content_hash": card.content_hash}
                for card in verified_evidence
            ],
            "excluded_evidence_count": len(evidence) - len(verified_evidence),
        }
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

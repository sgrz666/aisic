from __future__ import annotations

from sqlalchemy.orm import Session

from edusci.domain.flow import FlowStage, transition_stage
from edusci.memory.models import Project, TaskRecord
from edusci.services.projects import _task


def run_study_design(
    session: Session, project: Project, task: TaskRecord | None = None
):
    def build() -> None:
        if project.stage != FlowStage.DESIGN.value:
            raise ValueError("当前阶段不能生成研究设计")
        variables = project.research_problem.get("variables", [])
        route = project.route or project.suggested_route
        base = {
            "route": route,
            "hypotheses": [
                {
                    "id": "H1",
                    "statement": f"{variables[0]}与{variables[1]}存在可检验关系"
                    if len(variables) >= 2
                    else "核心变量之间存在可检验关系",
                    "status": "待验证",
                }
            ],
            "ethics_notes": ["参与自愿并取得知情同意", "不收集非必要的直接身份信息"],
        }
        if route == "B":
            base["questionnaire"] = {
                "title": f"{project.title}调查问卷",
                "items": [
                    {"id": "Q1", "dimension": "基本信息", "text": "您的专业类别是？", "type": "single_choice"},
                    {"id": "Q2", "dimension": "使用经验", "text": "您使用生成式 AI 的频率是？", "type": "likert5"},
                    {"id": "Q3", "dimension": "AI焦虑", "text": "我担心 AI 会削弱我的专业竞争力。", "type": "likert5"},
                    {"id": "Q4", "dimension": "AI焦虑", "text": "面对快速发展的 AI 技术，我感到不安。", "type": "likert5"},
                    {"id": "Q5", "dimension": "技术自我效能", "text": "我有信心学会使用新的 AI 工具。", "type": "likert5"},
                    {"id": "Q6", "dimension": "技术自我效能", "text": "我能判断 AI 输出是否可靠。", "type": "likert5"},
                ],
                "variable_item_map": {
                    "专业": ["Q1"],
                    "AI焦虑得分": ["Q3", "Q4"],
                    "技术自我效能": ["Q5", "Q6"],
                },
                "codebook": {"likert5": {"1": "非常不同意", "5": "非常同意"}},
            }
            target = FlowStage.WAITING_FOR_DATA
        elif route == "A":
            base["analysis_plan"] = {"methods": ["描述统计", "趋势分析", "组间比较"]}
            target = FlowStage.ANALYSIS
        else:
            base["synthesis_plan"] = {"sections": ["概念界定", "证据冲突", "知识缺口", "后续验证"]}
            target = FlowStage.REPORT
        project.study_design = base
        project.stage = transition_stage(FlowStage(project.stage), target).value

    return _task(session, project, "study_design", build, task)

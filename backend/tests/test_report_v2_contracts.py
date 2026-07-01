import pytest
from pydantic import ValidationError

from edusci.reporting.contracts import ResearchReportV2


def valid_report_payload() -> dict:
    return {
        "schema_version": 2,
        "paper_title": "生成式人工智能使用与大学生AI焦虑的可行性研究",
        "abstract": "背景：生成式人工智能进入大学学习场景后，其使用方式与学生焦虑体验之间的关系仍缺少直接证据。"
        "问题：既有材料没有同时测量人工智能使用、AI焦虑与一般心理健康，因而不能支持因果结论。"
        "方法：本研究先用可追溯文献界定变量，再以问卷数据执行量表构造、信度检验、描述统计和相关分析，"
        "并为后续真实样本设计回归与稳健性检验。数据：当前仅使用模拟数据验证分析流程。"
        "结果：模拟分析可输出均值、置信区间和相关系数，但不能据此推断现实人群效应。"
        "贡献：研究计划将数据性质、统计边界和后续采集要求显式分离，为真实调查提供可复现方案。"
        "在正式实施中还需使用经过许可的量表，完成知情同意、匿名化和样本量论证，并以独立样本复核。",
        "keywords": ["生成式人工智能", "AI焦虑", "大学生", "可行性研究"],
        "problem_statement": {
            "current_limitation": "现有证据未直接覆盖AI使用与心理健康的关系。",
            "knowledge_gap": "缺少同一研究中的构念测量和真实样本。",
            "research_question": "AI使用频率与AI焦虑、技术自我效能如何关联？",
            "evidence_ids": ["e1"],
        },
        "rationale": {
            "innovation": "分离模拟可行性与真实验证。",
            "reasoning_chain": ["界定构念", "核验证据", "构造量表", "检验关联"],
            "evidence_ids": ["e1"],
        },
        "hypotheses": [{
            "id": "H1", "null_hypothesis": "变量之间无相关", "alternative_hypothesis": "变量之间存在相关",
            "direction": "双侧", "falsification_criterion": "置信区间包含零且证据不足",
        }],
        "technical_details": [{
            "purpose": "相关检验", "method": "Pearson相关", "stack": ["pandas", "scipy"],
            "parameters": {"alpha": 0.05}, "execution_status": "executed", "rationale": "连续量表得分",
        }],
        "datasets": {
            "source": [],
            "simulation_input": [{
                "name": "模拟问卷", "origin_type": "synthetic_demo", "role": "流程验证",
                "rows": 120, "columns": ["Q3", "Q4"], "provenance_url": "", "license_name": "",
                "content_hash": "abc", "limitations": ["非真实调查"],
            }],
            "target": {
                "population": "在校大学生", "features": ["AI使用频率", "AI焦虑", "心理健康"],
                "label": "心理健康量表得分", "minimum_sample_size": 300,
                "collection_period": "一个学期", "format": "匿名CSV", "ethics": ["知情同意"],
            },
        },
        "methods": [{"step": 1, "name": "数据清洗", "input": "原始问卷", "procedure": "检查缺失和异常", "output": "分析数据"}],
        "experiments": {
            "baselines": [{"name": "零模型", "description": "仅含截距", "purpose": "比较解释增益"}],
            "metrics": [{"name": "Pearson r", "definition": "线性相关强度", "success_criterion": "报告95%CI"}],
            "validation_design": "独立样本复核", "robustness_checks": ["Spearman相关"],
        },
        "results": {
            "kind": "simulation_feasibility", "status": "可行性已验证，现实效应待验证", "sample_size": 120,
            "data_quality": {"missing_cells": 0}, "statistical_findings": [],
            "formulas": ["Y=β0+β1X+ε"], "feasibility_conclusion": "流程可执行", "limitations": ["模拟数据"],
        },
        "limitations_ethics": {
            "causal_boundary": "横断面相关不能推断因果", "sample_limitations": ["模拟样本"],
            "privacy": ["匿名化"], "consent": ["真实采集前取得知情同意"],
        },
        "references": [{
            "evidence_id": "e1", "authors": ["张三"], "title": "相关研究", "source": "教育研究",
            "year": 2024, "doi": "10.1/example", "url": "https://doi.org/10.1/example",
            "reference_type": "J", "formatted": "张三. 相关研究[J]. 教育研究, 2024.",
        }],
    }


def test_research_report_v2_accepts_all_required_sections() -> None:
    report = ResearchReportV2.model_validate(valid_report_payload())
    assert report.schema_version == 2
    assert report.results.kind == "simulation_feasibility"
    assert report.datasets.source == []


def test_research_report_v2_rejects_short_abstract_and_missing_reasoning_chain() -> None:
    payload = valid_report_payload()
    payload["abstract"] = "过短"
    payload["rationale"]["reasoning_chain"] = ["一步"]
    with pytest.raises(ValidationError):
        ResearchReportV2.model_validate(payload)

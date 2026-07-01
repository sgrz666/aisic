from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edusci.analysis.engine_v2 import analyze_questionnaire
from edusci.analysis.provenance import classify_dataset_origin
from edusci.analysis.storage import LocalObjectStore
from edusci.memory.models import (
    DatasetDeclarationRecord,
    DatasetRecord,
    EvidenceCard,
    KnowledgeEntity,
    Project,
    ReportArtifactRecord,
)
from edusci.reporting.contracts import ResearchReportV2


class ReportContextBuilder:
    """Build the trusted, deterministic report before any model-authored prose."""

    def build(self, session: Session, project: Project) -> tuple[dict, dict]:
        return _build_report(session, project)


class ReportComposer:
    """Let Qwen improve prose while keeping evidence, data and statistics immutable."""

    _NARRATIVE_KEYS = (
        "paper_title",
        "abstract",
        "keywords",
        "problem_statement",
        "rationale",
    )

    def compose(self, trusted_report: dict, model_provider=None) -> dict:
        if model_provider is None:
            return trusted_report

        prompt_context = {
            key: trusted_report[key]
            for key in self._NARRATIVE_KEYS
        }
        prompt_context["evidence"] = [
            {
                "evidence_id": item["evidence_id"],
                "title": item["title"],
                "formatted": item["formatted"],
            }
            for item in trusted_report["references"]
        ]
        prompt_context["result_boundary"] = {
            "kind": trusted_report["results"]["kind"],
            "status": trusted_report["results"]["status"],
            "sample_size": trusted_report["results"]["sample_size"],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是教育研究报告撰稿人。仅返回 JSON，并且只能改写 paper_title、"
                    "abstract、keywords、problem_statement 的三个文本字段，以及 rationale "
                    "的 innovation 和 reasoning_chain。不得新增事实、引文、统计值或数据源；"
                    "必须保持模拟数据和因果边界。摘要应包含背景、问题、方法、数据性质、"
                    "结果边界和贡献。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt_context, ensure_ascii=False)},
        ]
        for attempt in range(3):
            try:
                payload = model_provider.complete_json("generation", messages)
                candidate = self._merge_narrative(trusted_report, payload)
                return self._validate_with_compatibility(candidate)
            except Exception as exc:
                if attempt == 2:
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": f"上一次输出未通过 ResearchReportV2 校验：{exc}。请修复后仅返回允许字段。",
                    }
                )
        return trusted_report

    @staticmethod
    def _merge_narrative(trusted_report: dict, payload: dict) -> dict:
        candidate = deepcopy(trusted_report)
        for key in ("paper_title", "abstract", "keywords"):
            if key in payload:
                candidate[key] = payload[key]
        for section, text_keys in {
            "problem_statement": (
                "current_limitation",
                "knowledge_gap",
                "research_question",
            ),
            "rationale": ("innovation", "reasoning_chain"),
        }.items():
            incoming = payload.get(section)
            if not isinstance(incoming, dict):
                continue
            for key in text_keys:
                if key in incoming:
                    candidate[section][key] = incoming[key]
        return candidate

    @staticmethod
    def _validate_with_compatibility(candidate: dict) -> dict:
        validated = ResearchReportV2.model_validate(candidate).model_dump(mode="json")
        validated.update(
            {
                "title": validated["paper_title"],
                "problem": validated["problem_statement"]["current_limitation"],
                "rationale_text": validated["rationale"]["innovation"],
                "methods_text": "；".join(item["name"] for item in validated["methods"]),
                "results_text": validated["results"]["status"],
                "result_kind": candidate.get("result_kind", "expected_only"),
                "excluded_evidence_count": candidate.get("excluded_evidence_count", 0),
            }
        )
        return validated


class ReportTrustGuard:
    """Revalidate the final contract without allowing advisory prose to relax checks."""

    def review(self, report: dict, deterministic_review: dict) -> dict:
        ResearchReportV2.model_validate(report)
        review = deepcopy(deterministic_review)
        review["checks"]["schema"] = {
            "status": "PASS",
            "message": "ResearchReportV2 字段完整且模型未改写受保护字段",
        }
        return review


def _gbt_reference(session: Session, card: EvidenceCard) -> dict:
    entity = session.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.project_id == card.project_id,
            KnowledgeEntity.entity_type == "Source",
            KnowledgeEntity.content_hash == card.content_hash,
        )
    )
    metadata = entity.payload if entity is not None else {}
    authors = list(metadata.get("authors") or [])
    year = metadata.get("year")
    source_title = str(metadata.get("source_title") or "")
    volume = str(metadata.get("volume") or "")
    issue = str(metadata.get("issue") or "")
    pages = str(metadata.get("pages") or "")
    doi = str(metadata.get("doi") or (card.locator if card.locator.startswith("10.") else ""))
    reference_type = str(metadata.get("reference_type") or ("J" if source_title else "EB/OL"))
    author_text = ", ".join(authors) if authors else "[作者不详]"
    if reference_type == "J":
        source_part = f"{source_title}, {year or '年份不详'}"
        if volume:
            source_part += f", {volume}"
        if issue:
            source_part += f"({issue})"
        if pages:
            source_part += f": {pages}"
        formatted = f"{author_text}. {card.title}[J]. {source_part}."
    else:
        formatted = f"{author_text}. {card.title}[EB/OL]. {card.source_url}."
    if doi:
        formatted += f" DOI:{doi}."
    return {
        "evidence_id": card.id,
        "authors": authors,
        "title": card.title,
        "source": source_title,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "url": card.source_url,
        "reference_type": reference_type,
        "formatted": formatted,
    }


def _dataset_context(session: Session, project: Project) -> tuple[DatasetRecord | None, dict]:
    dataset_id = (project.analysis_result or {}).get("dataset_id")
    dataset = session.get(DatasetRecord, dataset_id) if dataset_id else None
    if dataset is None:
        return None, {"origin_type": "unknown", "confirmed": False}
    declaration = session.scalar(
        select(DatasetDeclarationRecord).where(
            DatasetDeclarationRecord.dataset_id == dataset.id
        )
    )
    if declaration is not None:
        return dataset, {
            "origin_type": declaration.origin_type,
            "confirmed": declaration.confirmed,
            "source_name": declaration.source_name,
            "source_url": declaration.source_url,
            "license_name": declaration.license_name,
            "collection_period": declaration.collection_period,
        }
    return dataset, {
        "origin_type": classify_dataset_origin(dataset.file_name),
        "confirmed": False,
        "source_name": dataset.file_name,
        "source_url": "",
        "license_name": "",
        "collection_period": "",
    }


def _construct_alignment(project: Project, columns: list[str]) -> tuple[bool, str]:
    idea = f"{project.idea_text} {(project.research_problem or {}).get('problem_statement', '')}"
    if "心理健康" not in idea:
        return True, "研究问题未要求整体心理健康构念。"
    direct_markers = ("心理健康", "PHQ", "GAD", "抑郁", "生活满意度", "幸福感")
    if any(marker.lower() in column.lower() for marker in direct_markers for column in columns):
        return True, "数据包含与心理健康直接对应的测量字段。"
    return False, "研究问题关注整体心理健康，但当前字段仅覆盖AI焦虑或技术自我效能。"


def _build_report(session: Session, project: Project) -> tuple[dict, dict]:
    all_evidence = list(
        session.scalars(
            select(EvidenceCard).where(
                EvidenceCard.project_id == project.id,
                EvidenceCard.trust_status == "PASS",
            )
        )
    )
    source_entities = list(
        session.scalars(
            select(KnowledgeEntity).where(
                KnowledgeEntity.project_id == project.id,
                KnowledgeEntity.entity_type == "Source",
            )
        )
    )
    refreshed_hashes = {
        entity.content_hash
        for entity in source_entities
        if entity.content_hash and (entity.payload or {}).get("refresh_v2")
    }
    evidence = (
        [card for card in all_evidence if card.content_hash in refreshed_hashes]
        if refreshed_hashes
        else all_evidence
    )
    references = [_gbt_reference(session, card) for card in evidence]
    evidence_ids = [card.id for card in evidence]
    dataset, declaration = _dataset_context(session, project)
    columns = list((dataset.data_schema or {}).get("columns", [])) if dataset else []
    questionnaire = (project.study_design or {}).get("questionnaire", {})
    analysis_v2: dict = {}
    if dataset is not None:
        try:
            frame = LocalObjectStore.read_dataframe(dataset.storage_path)
            analysis_v2 = analyze_questionnaire(frame, questionnaire)
        except (OSError, ValueError):
            analysis_v2 = {}

    origin = declaration["origin_type"]
    descriptor = {
        "name": declaration.get("source_name") or (dataset.file_name if dataset else "待确认数据"),
        "origin_type": origin,
        "role": "研究流程与统计可行性验证" if origin == "synthetic_demo" else "实证分析",
        "rows": dataset.row_count if dataset else None,
        "columns": columns,
        "provenance_url": declaration.get("source_url", ""),
        "license_name": declaration.get("license_name", ""),
        "content_hash": "",
        "limitations": ["该数据为模拟数据，不能代表现实大学生群体"]
        if origin == "synthetic_demo"
        else (["数据来源尚未人工确认"] if origin == "unknown" else []),
    }
    source_datasets = [descriptor] if origin in {"real_collected", "public_official"} else []
    simulations = [descriptor] if origin == "synthetic_demo" else []
    if origin in {"real_collected", "public_official"}:
        result_kind = "observed_empirical"
    elif origin == "synthetic_demo":
        result_kind = "simulation_feasibility"
    else:
        result_kind = "expected_only"

    findings = []
    for finding in analysis_v2.get("correlation_tests", []):
        estimate = finding.get("estimate")
        findings.append(
            {
                "method": "Pearson相关",
                "variables": finding.get("variables", []),
                "estimate": estimate,
                "p_value": finding.get("p_value"),
                "confidence_interval_95": finding.get("confidence_interval_95", []),
                "effect_size": finding.get("effect_size"),
                "interpretation": (
                    "变量呈负相关" if estimate is not None and estimate < 0 else "变量呈正相关"
                )
                + "；该结果仅用于模拟流程验证。"
                if result_kind == "simulation_feasibility"
                else "变量之间的线性关联应结合置信区间解释。",
            }
        )
    if not findings:
        for variable, summary in (project.analysis_result or {}).get("descriptive", {}).items():
            count = int(summary.get("count") or 0)
            mean = summary.get("mean")
            std = summary.get("std")
            interval: list[float | None] = [None, None]
            if count > 1 and mean is not None and std is not None:
                margin = 1.96 * float(std) / math.sqrt(count)
                interval = [float(mean) - margin, float(mean) + margin]
            findings.append(
                {
                    "method": "描述统计",
                    "variables": [str(variable)],
                    "estimate": mean,
                    "p_value": None,
                    "confidence_interval_95": interval,
                    "effect_size": None,
                    "interpretation": "报告均值及95%置信区间，不作因果解释。",
                }
            )

    aligned, alignment_message = _construct_alignment(project, columns)
    title = (
        "生成式人工智能使用、AI焦虑与技术自我效能的可行性研究"
        if "AI" in project.idea_text.upper() or "ai" in project.idea_text
        else f"{project.title}的科学假设与验证研究计划"
    )
    abstract = (
        "背景：生成式人工智能快速进入大学学习与就业准备场景，学生的使用经验、AI焦虑和技术自我效能"
        "可能共同影响其适应过程，但现有项目证据尚不足以确认对整体心理健康的现实影响。"
        "问题：当前问卷没有使用经过验证的整体心理健康结果指标，且数据来源性质必须与实证结论严格区分。"
        "方法：本研究采用可追溯文献综述、变量操作化、问卷量表构造、内部一致性检验、描述统计、"
        "Pearson相关及后续回归与稳健性分析，所有统计均由受控函数执行。"
        f"数据：当前分析包含{dataset.row_count if dataset else 0}条记录，数据性质为{origin}。"
        "结果：现阶段仅能检验分析流程、量表构造和变量关联的计算可行性；若数据为模拟数据，相关系数"
        "不能外推至现实大学生群体，也不能支持AI发展导致心理健康变化的因果命题。"
        "贡献：本计划将证据来源、Source数据、模拟输入与Target真实采集要求分离，并给出可证伪假设、"
        "基线模型、评价指标和伦理边界，为后续真实调查和独立样本复核提供可执行方案。"
    )
    report = {
        "schema_version": 2,
        "paper_title": title,
        "abstract": abstract,
        "keywords": ["生成式人工智能", "AI焦虑", "技术自我效能", "大学生"],
        "problem_statement": {
            "current_limitation": "既有材料未同时覆盖AI使用、AI焦虑和经过验证的整体心理健康结果。",
            "knowledge_gap": alignment_message,
            "research_question": "AI使用频率与AI焦虑、技术自我效能之间存在何种可复核关联？",
            "evidence_ids": evidence_ids[:4],
        },
        "rationale": {
            "innovation": "将模拟可行性、现实实证和未来Target数据分层，避免以流程输出替代现实证据。",
            "reasoning_chain": [
                "界定AI使用、AI焦虑、技术自我效能和心理健康构念",
                "仅使用可追溯文献形成问题边界",
                "根据问卷题项构造量表并检验内部一致性",
                "以基线统计和置信区间评估关联强度",
                "在真实Target样本中复核并限制因果解释",
            ],
            "evidence_ids": evidence_ids[:4],
        },
        "hypotheses": [
            {
                "id": "H1",
                "null_hypothesis": "AI使用频率与AI焦虑得分不存在统计关联。",
                "alternative_hypothesis": "AI使用频率与AI焦虑得分存在统计关联。",
                "direction": "双侧",
                "falsification_criterion": "95%置信区间包含零且独立样本未能复现。",
            },
            {
                "id": "H2",
                "null_hypothesis": "技术自我效能与AI焦虑得分不存在统计关联。",
                "alternative_hypothesis": "技术自我效能与AI焦虑得分存在统计关联。",
                "direction": "双侧",
                "falsification_criterion": "控制专业与AI使用后效应不稳定或置信区间包含零。",
            },
        ],
        "technical_details": [
            {"purpose": "量表构造", "method": "题项均值与缺失规则", "stack": ["pandas"], "parameters": {"minimum_items": 2}, "execution_status": "executed" if analysis_v2 else "planned", "rationale": "将多题项映射为可解释构念得分。"},
            {"purpose": "信度检验", "method": "Cronbach's alpha与Spearman-Brown", "stack": ["pandas", "numpy"], "parameters": {"threshold": 0.7}, "execution_status": "executed" if analysis_v2 else "planned", "rationale": "评估量表内部一致性。"},
            {"purpose": "关联检验", "method": "Pearson相关与95%置信区间", "stack": ["scipy"], "parameters": {"alpha": 0.05}, "execution_status": "executed" if findings else "planned", "rationale": "量化连续得分之间的线性关联。"},
            {"purpose": "真实样本复核", "method": "OLS回归与稳健标准误", "stack": ["statsmodels"], "parameters": {"alpha": 0.05}, "execution_status": "future_recommendation", "rationale": "在控制专业、年级和AI使用后评估关联。"},
        ],
        "datasets": {
            "source": source_datasets,
            "simulation_input": simulations,
            "target": {
                "population": "中国高校在校大学生",
                "features": ["AI使用频率", "AI焦虑量表", "技术自我效能", "专业", "年级", "心理健康有效量表"],
                "label": "经过验证的心理健康量表得分",
                "minimum_sample_size": 300,
                "collection_period": "至少一个完整学期",
                "format": "匿名CSV/XLSX及变量字典",
                "ethics": ["知情同意", "数据最小化", "去标识化", "伦理审批"],
            },
        },
        "methods": [
            {"step": 1, "name": "证据筛选", "input": "检索结果", "procedure": "按相关性、可追溯性和研究类型筛选", "output": "证据卡"},
            {"step": 2, "name": "变量操作化", "input": "研究问题与问卷", "procedure": "建立构念、题项和字段映射", "output": "变量字典"},
            {"step": 3, "name": "质量检查", "input": "原始数据", "procedure": "检查缺失、重复、范围和PII", "output": "质量报告"},
            {"step": 4, "name": "量表构造", "input": "有效题项", "procedure": "按codebook计分并计算量表均值", "output": "构念得分"},
            {"step": 5, "name": "统计分析", "input": "分析数据", "procedure": "执行信度、描述统计、相关与回归", "output": "统计结果"},
            {"step": 6, "name": "稳健性复核", "input": "主分析结果", "procedure": "使用替代指标和独立样本复核", "output": "稳健性结论"},
        ],
        "experiments": {
            "baselines": [
                {"name": "零模型", "description": "仅含截距的模型", "purpose": "评估解释变量带来的增量"},
                {"name": "控制变量模型", "description": "仅含专业、年级等控制变量", "purpose": "比较核心变量的额外解释力"},
            ],
            "metrics": [
                {"name": "Cronbach's alpha", "definition": "内部一致性信度", "success_criterion": "优先达到0.70并结合题项数解释"},
                {"name": "Pearson r及95%CI", "definition": "线性关联强度与不确定性", "success_criterion": "报告效应量、区间和样本量"},
                {"name": "调整R²", "definition": "控制模型复杂度后的解释度", "success_criterion": "相对基线有稳定增量"},
            ],
            "validation_design": "训练/分析规则预先固定，并在独立真实样本中复核。",
            "robustness_checks": ["Spearman相关", "异常值敏感性", "分专业分层", "替代量表"],
        },
        "results": {
            "kind": result_kind,
            "status": "模拟流程可行，现实效应待真实样本验证" if result_kind == "simulation_feasibility" else "按数据来源解释结果",
            "sample_size": dataset.row_count if dataset else None,
            "data_quality": dataset.quality_report if dataset else {},
            "statistical_findings": findings,
            "formulas": ["Y_i = β_0 + β_1 X_i + β_2 C_i + ε_i", "H_0: β_1 = 0；H_1: β_1 ≠ 0"],
            "feasibility_conclusion": "受控流程能够生成量表、信度和相关结果；现实推断取决于真实Target数据。",
            "limitations": descriptor["limitations"] + ([alignment_message] if not aligned else []),
        },
        "limitations_ethics": {
            "causal_boundary": "横断面关联不能证明AI使用导致心理健康变化。",
            "sample_limitations": descriptor["limitations"] + ([alignment_message] if not aligned else []),
            "privacy": ["不保留直接身份信息", "公开结果仅报告汇总统计"],
            "consent": ["真实采集前取得知情同意", "允许参与者撤回"],
        },
        "references": references,
        "appendices": {
            "questionnaire": questionnaire,
            "analysis_details": {
                "derived_scales": analysis_v2.get("derived_scales", {}),
                "reliability": analysis_v2.get("reliability", {}),
                "analysis_plan": analysis_v2.get("analysis_plan", {}),
            },
        },
    }
    validated = ResearchReportV2.model_validate(report).model_dump(mode="json")
    validated.update(
        {
            "title": validated["paper_title"],
            "problem": validated["problem_statement"]["current_limitation"],
            "rationale_text": validated["rationale"]["innovation"],
            "methods_text": "；".join(item["name"] for item in validated["methods"]),
            "results_text": validated["results"]["status"],
            "result_kind": "observed" if dataset is not None else "expected_only",
            "excluded_evidence_count": len(project.evidence_cards) - len(evidence),
        }
    )
    review = trust_review_v2(validated, project, declaration, aligned, alignment_message)
    return validated, review


def trust_review_v2(
    report: dict,
    project: Project,
    declaration: dict,
    construct_aligned: bool,
    alignment_message: str,
) -> dict:
    references = report.get("references", [])
    citation_status = "BLOCK" if not references else (
        "WARN" if any(not item.get("authors") or not item.get("year") for item in references) else "PASS"
    )
    dataset_status = "WARN" if declaration.get("origin_type") == "unknown" else "PASS"
    results = report["results"]
    statistics_status = (
        "BLOCK"
        if results["kind"] == "observed_empirical" and not results["statistical_findings"]
        else "PASS"
    )
    checks = {
        "schema": {"status": "PASS", "message": "ResearchReportV2字段完整"},
        "citation": {"status": citation_status, "message": "引用均来自已核验证据；缺失书目信息会降级"},
        "dataset_provenance": {"status": dataset_status, "message": f"数据来源类型：{declaration.get('origin_type')}"},
        "statistics": {"status": statistics_status, "message": "结果类型与统计输出一致"},
        "construct_alignment": {"status": "PASS" if construct_aligned else "WARN", "message": alignment_message},
        "ethics": {"status": "PASS", "message": "包含隐私、知情同意和因果边界"},
    }
    if project.route == "D":
        checks["logic"] = {"status": "BLOCK", "message": "探索性路径不允许形成确定结论"}
    statuses = {item["status"] for item in checks.values()}
    overall = "BLOCK" if "BLOCK" in statuses else "WARN" if "WARN" in statuses else "PASS"
    return {"overall": overall, "checks": checks, "revision_round": 0, "schema_version": 2}


def regenerate_report_v2(
    session: Session,
    project: Project,
    *,
    refresh_evidence: bool = True,
    model_provider=None,
    planner=None,
    literature_scout=None,
) -> ReportArtifactRecord:
    if refresh_evidence and planner is not None and literature_scout is not None:
        plan = planner.plan(project.idea_text)
        concepts = list(plan.concepts)
        for variable in plan.variables:
            concepts.extend(variable.aliases_en)
            concepts.extend(variable.aliases_zh)
        discovery = literature_scout.discover(plan.literature_queries, concepts)
        for candidate in discovery.candidates:
            if candidate.exclusion_reason or candidate.relevance_score < 55:
                continue
            raw = "|".join(
                (
                    candidate.title,
                    candidate.url,
                    candidate.doi or str(candidate.year or "online"),
                    candidate.abstract,
                )
            )
            content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            card = session.scalar(
                select(EvidenceCard).where(
                    EvidenceCard.project_id == project.id,
                    EvidenceCard.content_hash == content_hash,
                )
            )
            if card is None:
                card = EvidenceCard(
                    project_id=project.id,
                    title=candidate.title,
                    source_type="scholarly",
                    source_url=candidate.url,
                    locator=candidate.doi or str(candidate.year or "online"),
                    excerpt=candidate.abstract,
                    claim=candidate.abstract,
                    content_hash=content_hash,
                    trust_status="PASS",
                )
                session.add(card)
                session.flush()
            entity = session.scalar(
                select(KnowledgeEntity).where(
                    KnowledgeEntity.project_id == project.id,
                    KnowledgeEntity.entity_type == "Source",
                    KnowledgeEntity.content_hash == content_hash,
                )
            )
            metadata = {
                "authors": candidate.authors,
                "year": candidate.year,
                "source_title": candidate.source_title,
                "volume": candidate.volume,
                "issue": candidate.issue,
                "pages": candidate.pages,
                "publisher": candidate.publisher,
                "doi": candidate.doi,
                "reference_type": candidate.reference_type,
                "relevance_score": candidate.relevance_score,
                "refresh_v2": True,
            }
            if entity is None:
                session.add(
                    KnowledgeEntity(
                        project_id=project.id,
                        entity_type="Source",
                        name=candidate.title,
                        content_hash=content_hash,
                        payload=metadata,
                    )
                )
            else:
                entity.payload = metadata
                session.add(entity)
        session.commit()
    existing_count = session.scalar(
        select(func.count()).select_from(ReportArtifactRecord).where(
            ReportArtifactRecord.project_id == project.id
        )
    ) or 0
    if existing_count == 0 and project.report:
        session.add(
            ReportArtifactRecord(
                project_id=project.id,
                version=1,
                schema_version=int(project.report.get("schema_version", 1)),
                report_json=project.report,
                review_json=project.review or {},
                generation_config={"legacy_snapshot": True},
            )
        )
        session.flush()
    version = int(
        session.scalar(
            select(func.max(ReportArtifactRecord.version)).where(
                ReportArtifactRecord.project_id == project.id
            )
        )
        or 0
    ) + 1
    trusted_report, deterministic_review = ReportContextBuilder().build(session, project)
    report = ReportComposer().compose(trusted_report, model_provider)
    review = ReportTrustGuard().review(report, deterministic_review)
    artifact = ReportArtifactRecord(
        project_id=project.id,
        version=version,
        schema_version=2,
        report_json=report,
        review_json=review,
        generation_config={
            "refresh_evidence": refresh_evidence,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    project.report = report
    project.review = review
    session.add_all([artifact, project])
    session.commit()
    session.refresh(artifact)
    return artifact

from pathlib import Path

from sqlalchemy import inspect

from edusci.autonomy.contracts import AutonomousStatus, ResearchPlan
from edusci.memory.database import build_session_factory
from edusci.memory.models import AutonomousRunRecord, NodeCheckpointRecord


def test_autonomy_contract_and_tables(tmp_path: Path) -> None:
    plan = ResearchPlan.model_validate(
        {
            "problem_statement": "人口变化对教育资源的影响",
            "concepts": ["人口变化", "教育资源"],
            "variables": [
                {
                    "name": "人口变化",
                    "aliases_zh": ["学龄人口"],
                    "aliases_en": ["school-age population"],
                }
            ],
            "population": "基础教育阶段",
            "geographies": ["CHN"],
            "time_range": {"start": 2015, "end": 2026},
            "literature_queries": [
                {
                    "query": "学龄人口 教育资源",
                    "language": "zh",
                    "purpose": "broad",
                }
            ],
            "data_requirements": [
                {
                    "concept": "school-age population",
                    "unit_hint": "people",
                    "required": True,
                }
            ],
        }
    )
    assert plan.time_range.end == 2026
    assert AutonomousStatus.AWAITING_ROUTE.value == "awaiting_route_confirmation"

    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'auto.db').as_posix()}"
    )
    with factory() as session:
        tables = set(inspect(session.get_bind()).get_table_names())
    assert AutonomousRunRecord.__tablename__ in tables
    assert NodeCheckpointRecord.__tablename__ in tables


def test_research_plan_rejects_reversed_year_range() -> None:
    invalid = {
        "problem_statement": "测试",
        "concepts": ["测试"],
        "variables": [{"name": "变量"}],
        "population": "学生",
        "geographies": ["CHN"],
        "time_range": {"start": 2026, "end": 2015},
        "literature_queries": [
            {"query": "教育测试", "language": "zh", "purpose": "broad"}
        ],
        "data_requirements": [],
    }

    try:
        ResearchPlan.model_validate(invalid)
    except ValueError as exc:
        assert "开始年份不能晚于结束年份" in str(exc)
    else:
        raise AssertionError("倒置的年份范围必须被拒绝")

from __future__ import annotations

import os

from sqlalchemy import select

from edusci.api.schemas import ProjectCreate, SourceInput
from edusci.memory.database import build_session_factory
from edusci.memory.models import Project
from edusci.services.projects import create_project, run_evidence_build, run_gate, run_idea_parse


def sources(count: int, prefix: str) -> list[dict]:
    return [
        {
            "title": f"{prefix}参考资料 {index + 1}",
            "source_type": "journal" if index % 2 == 0 else "report",
            "url": f"https://example.edu/demo/{prefix}/{index + 1}",
            "locator": f"第 {index + 1} 节",
            "excerpt": f"这是用于演示证据追溯的第 {index + 1} 条事实。",
            "verified": True,
        }
        for index in range(count)
    ]


CASES = [
    ("A · 人口与教育资源", "人口变化对基础教育资源配置的影响", 5),
    ("B · 大学生 AI 焦虑", "分析大学生 AI 焦虑度与专业的关系", 1),
    ("C · 理论证据综合", "算法透明度与组织文化的理论关系", 5),
    ("D · 探索性问题", "人吃饭速度与眨眼频率的关系", 0),
]


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/edusci.db")
    session_factory = build_session_factory(database_url)
    with session_factory() as session:
        existing = set(session.scalars(select(Project.title)))
        created = 0
        for title, idea, count in CASES:
            if title in existing:
                continue
            project = create_project(
                session,
                ProjectCreate(title=title, idea_text=idea),
            )
            run_idea_parse(session, project)
            run_evidence_build(
                session,
                project,
                [SourceInput.model_validate(source) for source in sources(count, title[0])],
            )
            run_gate(session, project)
            created += 1
        print(f"演示数据准备完成：新增 {created} 个项目。")


if __name__ == "__main__":
    main()

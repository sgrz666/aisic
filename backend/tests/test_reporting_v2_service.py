from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from edusci.api.schemas import ProjectCreate, SourceInput
from edusci.app import create_app
from edusci.memory.models import (
    AutonomousRunRecord,
    ClaimEvidenceLinkRecord,
    KnowledgeEntity,
    Project,
    ProjectEvidenceUseRecord,
    ReportArtifactRecord,
    ResearchChunkRecord,
    ResearchClaimRecord,
    ResearchDocumentRecord,
    ResearchDocumentVersionRecord,
)
from edusci.services.analysis import save_dataset
from edusci.services.projects import create_project, run_evidence_build, run_idea_parse
from edusci.services.reporting_v2 import regenerate_report_v2
from edusci.services.reporting_v3 import regenerate_report_v3
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.planning import ResearchPlanner
from tests.autonomy_fakes import FakeLiteratureAdapter


class _StrictBlindReviewProvider:
    def __init__(self) -> None:
        self.review_schema_names: list[str] = []

    def complete_json(self, role, messages, schema=None):
        del messages
        if role == "synthesis" and schema is None:
            return {}
        if role == "review":
            assert schema is not None
            self.review_schema_names.append(schema.__name__)
            return schema.model_validate(
                {
                    "status": "PASS",
                    "summary": "All conclusions remain within the validated evidence.",
                    "issues": [],
                }
            ).model_dump(mode="json")
        raise AssertionError(f"unexpected role: {role}")


def _completed_legacy_project(app, tmp_path: Path):
    with app.state.session_factory() as session:
        project = create_project(
            session,
            ProjectCreate(
                title="AI与心理健康",
                idea_text="AI发展会加重大学生心理健康",
            ),
        )
        run_idea_parse(session, project)
        run_evidence_build(
            session,
            project,
            [
                SourceInput(
                    title="大学生AI焦虑研究",
                    source_type="journal",
                    url="https://doi.org/10.1/ai-anxiety",
                    locator="10.1/ai-anxiety",
                    excerpt="大学生人工智能焦虑与技术自我效能之间存在可测量的相关关系。",
                    verified=True,
                )
            ],
        )
        project.stage = "WAITING_FOR_DATA"
        project.route = "B"
        project.study_design = {
            "route": "B",
            "hypotheses": [{"id": "H1", "statement": "AI使用与AI焦虑相关"}],
            "questionnaire": {
                "variable_item_map": {
                    "AI焦虑得分": ["Q3", "Q4"],
                    "技术自我效能": ["Q5", "Q6"],
                }
            },
        }
        session.commit()
        dataset = save_dataset(
            session,
            app.state.object_store,
            project,
            "AI心理健康问卷_模拟答案_120份.csv",
            "text/csv",
            (
                "Q3_AI焦虑1,Q4_AI焦虑2,Q5_技术自我效能1,Q6_技术自我效能2\n"
                "1,1,5,5\n2,2,5,4\n3,3,4,4\n4,4,2,2\n5,5,1,1\n"
            ).encode(),
        )
        project.analysis_result = {
            "sample_size": 5,
            "dataset_id": dataset.id,
            "quality_report": dataset.quality_report,
        }
        project.report = {"title": "旧版报告", "result_kind": "observed"}
        project.review = {"overall": "PASS"}
        project.stage = "COMPLETED"
        session.commit()
        return project.id


def test_regeneration_preserves_legacy_version_and_marks_simulation(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'v2.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )
    with TestClient(app):
        project_id = _completed_legacy_project(app, tmp_path)
        with app.state.session_factory() as session:
            project = session.get(Project, project_id)
            assert project is not None
            artifact = regenerate_report_v2(session, project, refresh_evidence=False)
            artifacts = session.scalars(
                select(ReportArtifactRecord)
                .where(ReportArtifactRecord.project_id == project_id)
                .order_by(ReportArtifactRecord.version)
            ).all()

            assert artifact.version == 2
            assert len(artifacts) == 2
            assert artifacts[0].schema_version == 1
            report = artifact.report_json
            assert report["schema_version"] == 2
            assert report["datasets"]["source"] == []
            assert report["datasets"]["simulation_input"][0]["origin_type"] == "synthetic_demo"
            assert report["results"]["kind"] == "simulation_feasibility"
            assert artifact.review_json["overall"] != "PASS"
            assert artifact.review_json["checks"]["construct_alignment"]["status"] == "WARN"


def test_report_v3_only_promotes_claims_with_located_evidence(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'v3.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )
    with TestClient(app):
        project_id = _completed_legacy_project(app, tmp_path)
        with app.state.session_factory() as session:
            project = session.get(Project, project_id)
            run = AutonomousRunRecord(
                project_id=project_id,
                status="generating_report",
                current_iteration=2,
                source_count=4,
                fulltext_count=2,
                claim_count=2,
                coverage=100,
                counter_evidence_coverage=50,
                stop_reason="evidence_saturated",
            )
            session.add(run)
            session.flush()
            document = ResearchDocumentRecord(
                canonical_key="doi:10.1/deep",
                title="Located evidence",
                source_type="scholarly",
                canonical_url="https://doi.org/10.1/deep",
                license_name="CC BY 4.0",
            )
            session.add(document)
            session.flush()
            version = ResearchDocumentVersionRecord(
                document_id=document.id,
                content_hash="a" * 64,
                mime_type="application/pdf",
                storage_path="https://example.edu/deep.pdf",
            )
            session.add(version)
            session.flush()
            chunk = ResearchChunkRecord(
                version_id=version.id,
                chunk_index=0,
                locator="第 4 页",
                text="Population change affects education resource allocation.",
                text_hash="b" * 64,
            )
            supported = ResearchClaimRecord(
                claim_hash="c" * 64,
                statement="Population change affects education resource allocation.",
            )
            unsupported = ResearchClaimRecord(
                claim_hash="d" * 64,
                statement="This unsupported claim must not enter conclusions.",
            )
            session.add_all([chunk, supported, unsupported])
            session.flush()
            link = ClaimEvidenceLinkRecord(
                claim_id=supported.id,
                chunk_id=chunk.id,
                stance="supports",
                excerpt=chunk.text,
                excerpt_hash=chunk.text_hash,
                confidence=92,
                validation_status="validated",
                entailment_score=92,
            )
            session.add_all(
                [
                    link,
                    ProjectEvidenceUseRecord(
                        project_id=project_id,
                        run_id=run.id,
                        claim_id=supported.id,
                        assessment={"status": "accepted"},
                    ),
                    ProjectEvidenceUseRecord(
                        project_id=project_id,
                        run_id=run.id,
                        claim_id=unsupported.id,
                        assessment={"status": "candidate"},
                    ),
                ]
            )
            session.commit()

            artifact = regenerate_report_v3(session, project, refresh_evidence=False)

            assert artifact.schema_version == 3
            report = artifact.report_json
            assert report["schema_version"] == 3
            assert report["research_methodology"]["iterations"] == 2
            assert report["conclusions"] == []
            assert report["restricted"] is True
            assert report["evidence_ledger"][0]["locator"] == "第 4 页"
            assert artifact.review_json["checks"]["claim_grounding"]["status"] == "WARN"

            second_document = ResearchDocumentRecord(
                canonical_key="doi:10.1/deep-replication",
                title="Independent replication",
                source_type="scholarly",
                canonical_url="https://doi.org/10.1/deep-replication",
                license_name="CC BY 4.0",
            )
            session.add(second_document)
            session.flush()
            second_version = ResearchDocumentVersionRecord(
                document_id=second_document.id,
                content_hash="e" * 64,
                mime_type="text/html",
                storage_path="https://example.edu/replication",
            )
            session.add(second_version)
            session.flush()
            second_chunk = ResearchChunkRecord(
                version_id=second_version.id,
                chunk_index=0,
                locator="Results",
                text="Population change affects education resource allocation.",
                text_hash="f" * 64,
            )
            session.add(second_chunk)
            session.flush()
            second_link = ClaimEvidenceLinkRecord(
                claim_id=supported.id,
                chunk_id=second_chunk.id,
                stance="supports",
                excerpt=second_chunk.text,
                excerpt_hash=second_chunk.text_hash,
                confidence=88,
                validation_status="validated",
                entailment_score=88,
            )
            session.add(second_link)
            session.commit()

            corroborated = regenerate_report_v3(
                session, project, refresh_evidence=False
            ).report_json

            assert corroborated["restricted"] is False
            assert corroborated["conclusions"][0]["claim_id"] == supported.id
            assert set(corroborated["conclusions"][0]["evidence_ids"]) == {
                link.id,
                second_link.id,
            }

            provider = _StrictBlindReviewProvider()
            reviewed = regenerate_report_v3(
                session,
                project,
                refresh_evidence=False,
                model_provider=provider,
            )

            assert reviewed.review_json["agent_review"]["status"] == "PASS"
            assert provider.review_schema_names == ["_BlindReview"]


def test_report_regeneration_api_and_dataset_provenance(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'api-v2.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )
    with TestClient(app) as client:
        project_id = _completed_legacy_project(app, tmp_path)
        project = client.get(f"/api/v1/projects/{project_id}").json()
        dataset_id = project["analysis_result"]["dataset_id"]

        provenance = client.put(
            f"/api/v1/datasets/{dataset_id}/provenance",
            json={"origin_type": "synthetic_demo", "source_name": "比赛模拟问卷", "confirmed": True},
        )
        assert provenance.status_code == 200
        regenerated = client.post(
            f"/api/v1/projects/{project_id}/report-regenerations",
            json={"refresh_evidence": False},
        )
        assert regenerated.status_code == 202
        artifacts = client.get(f"/api/v1/projects/{project_id}/report-artifacts")
        assert artifacts.status_code == 200
        assert artifacts.json()[-1]["schema_version"] == 3


def test_regeneration_formats_stored_bibliography_as_gbt_7714(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'bib.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )
    with TestClient(app):
        project_id = _completed_legacy_project(app, tmp_path)
        with app.state.session_factory() as session:
            project = session.get(Project, project_id)
            assert project is not None
            card = project.evidence_cards[0]
            session.add(
                KnowledgeEntity(
                    project_id=project.id,
                    entity_type="Source",
                    name=card.title,
                    content_hash=card.content_hash,
                    payload={
                        "authors": ["Li Ming", "Wang Fang"],
                        "year": 2024,
                        "source_title": "Journal of Educational Psychology",
                        "volume": "12",
                        "issue": "3",
                        "pages": "10-22",
                        "doi": "10.1/ai-anxiety",
                        "reference_type": "J",
                    },
                )
            )
            session.commit()
            artifact = regenerate_report_v2(session, project, refresh_evidence=False)
            reference = artifact.report_json["references"][0]
            assert reference["authors"] == ["Li Ming", "Wang Fang"]
            assert "Journal of Educational Psychology" in reference["formatted"]
            assert "2024" in reference["formatted"]


def test_regeneration_refreshes_topic_specific_evidence(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'refresh.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )
    papers = [
        {
            "title": f"Generative AI anxiety and student mental health {index}",
            "doi": f"10.1/ai-health-{index}",
            "abstract": "Generative artificial intelligence anxiety and technology self-efficacy are associated with university student mental health outcomes.",
            "authors": ["Researcher A"],
            "year": 2025,
            "url": f"https://doi.org/10.1/ai-health-{index}",
            "source_title": "Journal of AI in Education",
        }
        for index in range(6)
    ]
    with TestClient(app):
        project_id = _completed_legacy_project(app, tmp_path)
        with app.state.session_factory() as session:
            project = session.get(Project, project_id)
            assert project is not None
            artifact = regenerate_report_v2(
                session,
                project,
                refresh_evidence=True,
                planner=ResearchPlanner(),
                literature_scout=LiteratureScout([FakeLiteratureAdapter(papers)]),
            )
            assert any("Generative AI anxiety" in item["title"] for item in artifact.report_json["references"])
            assert all(item["authors"] for item in artifact.report_json["references"])


def test_composer_allows_narrative_but_preserves_trusted_sections(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'composer.db').as_posix()}",
        storage_root=tmp_path / "files",
        task_mode="inline",
    )

    class NarrativeProvider:
        calls = 0

        def complete_json(self, role: str, messages: list[dict]) -> dict:
            self.calls += 1
            return {
                "paper_title": "大学生生成式人工智能焦虑与技术自我效能关系研究",
                "abstract": "本研究聚焦大学生使用生成式人工智能时出现的焦虑体验与技术自我效能差异。" * 12,
                "keywords": ["生成式人工智能", "AI焦虑", "技术自我效能"],
                "problem_statement": {
                    "current_limitation": "现有研究尚未同时核验人工智能焦虑、技术自我效能与心理健康的构念边界。",
                    "knowledge_gap": "当前项目缺少直接测量整体心理健康的有效量表，因此不能形成现实因果结论。",
                    "research_question": "大学生人工智能使用、焦虑与技术自我效能之间存在何种可复核关联？",
                    "evidence_ids": ["forged-evidence"],
                },
                "rationale": {
                    "innovation": "将模拟流程验证与真实样本推断分层，并明确后续复核条件。",
                    "reasoning_chain": ["界定构念", "锁定证据", "构造量表", "执行受控统计"],
                    "evidence_ids": ["forged-evidence"],
                },
                "datasets": {"source": [{"name": "forged"}]},
                "results": {"kind": "observed_empirical", "sample_size": 9999},
                "references": [{"title": "forged"}],
            }

    with TestClient(app):
        project_id = _completed_legacy_project(app, tmp_path)
        with app.state.session_factory() as session:
            project = session.get(Project, project_id)
            assert project is not None
            baseline = regenerate_report_v2(session, project, refresh_evidence=False)
            provider = NarrativeProvider()
            artifact = regenerate_report_v2(
                session,
                project,
                refresh_evidence=False,
                model_provider=provider,
            )

            assert provider.calls == 1
            assert artifact.report_json["paper_title"].startswith("大学生生成式")
            assert artifact.report_json["datasets"] == baseline.report_json["datasets"]
            assert artifact.report_json["results"] == baseline.report_json["results"]
            assert artifact.report_json["references"] == baseline.report_json["references"]
            assert (
                artifact.report_json["problem_statement"]["evidence_ids"]
                == baseline.report_json["problem_statement"]["evidence_ids"]
            )

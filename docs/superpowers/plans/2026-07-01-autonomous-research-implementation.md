# 教育智研受控全自动研究流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现从研究 Idea 自动规划、检索文献、发现和下载官方教育数据、评分分流、暂停确认、恢复分析、生成报告和复审的受控全自动流程。

**Architecture:** 新增 `edusci.autonomy` 包承载结构化契约、规划器、文献/数据 Scout、检查点和总编排器；外部来源通过白名单适配器接入。Qwen 只生成结构化计划，确定性执行器负责网络访问、状态推进和受控统计。`AutonomousRun` 与现有 S0–S6 项目阶段并存，inline 与 RQ 共用同一编排代码。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Pydantic、httpx、Redis/RQ、pandas/scipy/statsmodels、React/TypeScript、Vitest、Playwright。

---

## 文件结构

新增后端文件：

```text
backend/edusci/autonomy/
  __init__.py            包入口
  contracts.py           ResearchPlan、候选、事件等 Pydantic 契约
  planning.py            Qwen/确定性 ResearchPlanner
  literature.py          多轮文献发现、去重、排序和停止条件
  data_scout.py          数据候选聚合、评分、选择和下载
  checkpoints.py         输入哈希、检查点读写和幂等判断
  orchestrator.py        一键流程状态机与暂停/恢复
backend/edusci/integrations/datasets/
  __init__.py            适配器注册表
  base.py                DatasetSourceAdapter 协议和 HTTP 重试基类
  world_bank.py          World Bank Indicators
  unicef.py              UNICEF SDMX
  unesco.py              UNESCO UIS API
  moe.py                 教育部统计页面
backend/edusci/services/autonomy.py
                         API/RQ 共用的创建、查询、取消和恢复服务
backend/tests/autonomy_fakes.py
                         所有自动流程测试共用的模型、文献和数据适配器替身
```

修改：

```text
backend/edusci/memory/models.py
backend/edusci/api/schemas.py
backend/edusci/api/routes.py
backend/edusci/app.py
backend/edusci/tasks/jobs.py
backend/edusci/tasks/dispatcher.py
backend/edusci/services/projects.py
backend/edusci/services/analysis.py
backend/edusci/analysis/storage.py
backend/pyproject.toml
frontend/src/api.ts
frontend/src/types.ts
frontend/src/pages/WorkspacePage.tsx
frontend/src/styles.css
README.md
```

---

### Task 1: 自动运行契约与持久化模型

**Files:**
- Create: `backend/edusci/autonomy/__init__.py`
- Create: `backend/edusci/autonomy/contracts.py`
- Create: `backend/tests/autonomy_fakes.py`
- Modify: `backend/edusci/memory/models.py`
- Modify: `backend/edusci/api/schemas.py`
- Test: `backend/tests/test_autonomy_models.py`

- [ ] **Step 1: 写失败测试，锁定状态、表和唯一检查点**

```python
from sqlalchemy import inspect

from edusci.autonomy.contracts import AutonomousStatus, ResearchPlan
from edusci.memory.database import build_session_factory
from edusci.memory.models import AutonomousRunRecord, NodeCheckpointRecord


def test_autonomy_contract_and_tables(tmp_path):
    plan = ResearchPlan.model_validate({
        "problem_statement": "人口变化对教育资源的影响",
        "concepts": ["人口变化", "教育资源"],
        "variables": [
            {"name": "人口变化", "aliases_zh": ["学龄人口"], "aliases_en": ["school-age population"]}
        ],
        "population": "基础教育阶段",
        "geographies": ["CHN"],
        "time_range": {"start": 2015, "end": 2026},
        "literature_queries": [{"query": "学龄人口 教育资源", "language": "zh", "purpose": "broad"}],
        "data_requirements": [{"concept": "school-age population", "unit_hint": "people", "required": True}],
    })
    assert plan.time_range.end == 2026
    assert AutonomousStatus.AWAITING_ROUTE.value == "awaiting_route_confirmation"

    factory = build_session_factory(f"sqlite+pysqlite:///{(tmp_path / 'auto.db').as_posix()}")
    with factory() as session:
        tables = set(inspect(session.get_bind()).get_table_names())
    assert AutonomousRunRecord.__tablename__ in tables
    assert NodeCheckpointRecord.__tablename__ in tables
```

- [ ] **Step 2: 运行测试，确认因契约和模型不存在而失败**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_models.py -q`  
Expected: FAIL，提示 `No module named 'edusci.autonomy'`。

- [ ] **Step 3: 实现 Pydantic 契约**

`contracts.py` 定义以下公开类型：

```python
class AutonomousStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    SEARCHING_LITERATURE = "searching_literature"
    SEARCHING_DATASETS = "searching_datasets"
    RANKING_SOURCES = "ranking_sources"
    VALIDATING_EVIDENCE = "validating_evidence"
    AWAITING_ROUTE = "awaiting_route_confirmation"
    DESIGNING_STUDY = "designing_study"
    DOWNLOADING_DATASET = "downloading_dataset"
    ANALYZING = "analyzing"
    GENERATING_REPORT = "generating_report"
    REVIEWING = "reviewing"
    AWAITING_REAL_DATA = "awaiting_real_data"
    PAUSED_RISK = "paused_risk"
    FAILED = "failed"
    CANCELED = "canceled"
    COMPLETED = "completed"


class VariableSpec(BaseModel):
    name: str
    aliases_zh: list[str] = Field(default_factory=list)
    aliases_en: list[str] = Field(default_factory=list)


class YearRange(BaseModel):
    start: int = Field(ge=1900, le=2100)
    end: int = Field(ge=1900, le=2100)

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.end:
            raise ValueError("开始年份不能晚于结束年份")
        return self


class LiteratureQuery(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    language: Literal["zh", "en"]
    purpose: Literal["broad", "gap", "citation"]


class DataRequirement(BaseModel):
    concept: str
    unit_hint: str = ""
    required: bool = True


class ResearchPlan(BaseModel):
    problem_statement: str
    concepts: list[str]
    variables: list[VariableSpec]
    population: str
    geographies: list[str]
    time_range: YearRange
    literature_queries: list[LiteratureQuery]
    data_requirements: list[DataRequirement]
```

同时定义以下公开契约，后续任务只使用这些字段名：

```python
class LiteratureCandidate(BaseModel):
    source: str
    source_id: str
    title: str
    abstract: str = ""
    doi: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str
    license_url: str = ""
    citation_count: int = 0
    evidence_type: Literal["theory", "measurement", "method", "counter", "general"] = "general"
    relevance_score: int = Field(default=0, ge=0, le=100)
    exclusion_reason: str = ""


class SearchAttemptData(BaseModel):
    source: str
    query: str
    round_number: int
    result_count: int
    duration_ms: int
    error: str = ""


class DatasetCandidateData(BaseModel):
    source: str
    dataset_id: str
    title: str
    description: str = ""
    provenance_url: str
    download_url: str
    geographies: list[str] = Field(default_factory=list)
    start_year: int | None = None
    end_year: int | None = None
    unit: str = ""
    frequency: str = ""
    license_name: str = ""
    license_url: str = ""
    license_status: Literal["allowed", "review", "blocked"] = "review"
    fields: list[str] = Field(default_factory=list)
    variable_mapping: dict[str, str] = Field(default_factory=dict)
    variable_coverage: int = Field(default=0, ge=0, le=100)
    score: int = Field(default=0, ge=0, le=100)
    estimated_size_bytes: int | None = None
    excluded_reason: str = ""


class DatasetAssetData(BaseModel):
    candidate_id: str
    storage_path: str
    content_hash: str
    row_count: int
    column_count: int
    schema_json: dict
    quality_report: dict


class ProvenanceData(BaseModel):
    source: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    license_name: str
    license_url: str
    transformations: list[str]


class AutonomousEventData(BaseModel):
    run_id: str
    node: str
    message: str
    progress: int = Field(ge=0, le=100)
    timestamp: datetime


class CheckpointOutput(BaseModel):
    node_name: str
    input_hash: str
    output: dict
    reused: bool
```

- [ ] **Step 3a: 新增共享测试替身，避免后续测试自造不一致接口**

`backend/tests/autonomy_fakes.py` 提供：

```python
class FakeProvider:
    def __init__(self, response: dict):
        self.response = response
        self.calls = 0

    def complete_json(self, role: str, messages: list[dict]) -> dict:
        self.calls += 1
        return self.response


class FakeLiteratureAdapter:
    name = "fake_literature"

    def __init__(self, results: list[dict], fail: bool = False):
        self.results = results
        self.fail = fail
        self.calls = 0

    def search(self, query: str, limit: int) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("literature source unavailable")
        return self.results[:limit]

    def related(self, source_id: str, limit: int) -> list[dict]:
        return []


class FakeDatasetAdapter:
    name = "fake_dataset"

    def __init__(self, candidates: list[DatasetCandidateData], payload: bytes, fail: bool = False):
        self.candidates = candidates
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def search(self, requirement: DataRequirement, limit: int) -> list[DatasetCandidateData]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("dataset source unavailable")
        return self.candidates[:limit]

    def download(self, candidate: DatasetCandidateData, geography: list[str], years: YearRange) -> bytes:
        return self.payload


def make_dataset_candidate(**overrides) -> DatasetCandidateData:
    values = {
        "source": "world_bank",
        "dataset_id": "SP.POP.TOTL",
        "title": "Population, total",
        "provenance_url": "https://api.worldbank.org/v2/indicator/SP.POP.TOTL",
        "download_url": "https://api.worldbank.org/v2/country/CHN/indicator/SP.POP.TOTL",
        "geographies": ["CHN"],
        "start_year": 2015,
        "end_year": 2026,
        "unit": "people",
        "frequency": "annual",
        "license_name": "CC BY 4.0",
        "license_url": "https://datacatalog.worldbank.org/public-licenses",
        "license_status": "allowed",
        "fields": ["country", "year", "value"],
        "variable_mapping": {"school-age population": "value"},
        "variable_coverage": 100,
        "estimated_size_bytes": 1024,
    }
    values.update(overrides)
    return DatasetCandidateData.model_validate(values)


def make_research_plan() -> ResearchPlan:
    return ResearchPlan.model_validate({
        "problem_statement": "人口变化对基础教育资源配置的影响",
        "concepts": ["population", "education resources"],
        "variables": [{"name": "school-age population", "aliases_zh": ["学龄人口"], "aliases_en": []}],
        "population": "基础教育阶段",
        "geographies": ["CHN"],
        "time_range": {"start": 2015, "end": 2026},
        "literature_queries": [{"query": "school-age population education resources", "language": "en", "purpose": "broad"}],
        "data_requirements": [{"concept": "school-age population", "unit_hint": "people", "required": True}],
    })
```

- [ ] **Step 4: 新增七张表**

在 `models.py` 新增 `AutonomousRunRecord、ResearchPlanRecord、SearchAttemptRecord、DatasetCandidateRecord、DatasetAssetRecord、ProvenanceRecord、NodeCheckpointRecord`。`NodeCheckpointRecord` 对 `(run_id, node_name, input_hash)` 设置 `UniqueConstraint`；JSON 字段默认空对象，不修改现有表结构。

- [ ] **Step 5: 增加 API View Schema 并跑绿测试**

在 `api/schemas.py` 增加 `AutonomousRunCreate、AutonomousRunView、AutonomousRunRef、DatasetCandidateView`。运行：

`cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_models.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/edusci/autonomy backend/edusci/memory/models.py backend/edusci/api/schemas.py backend/tests/autonomy_fakes.py backend/tests/test_autonomy_models.py
git commit -m "feat: add autonomous research contracts and persistence"
```

---

### Task 2: ResearchPlanner 生成可执行研究计划

**Files:**
- Create: `backend/edusci/autonomy/planning.py`
- Modify: `backend/edusci/services/projects.py`
- Test: `backend/tests/test_autonomy_planning.py`

- [ ] **Step 1: 写失败测试**

```python
from edusci.autonomy.planning import ResearchPlanner


class FakeProvider:
    def complete_json(self, role, messages):
        assert role == "generation"
        return {
            "problem_statement": "人口变化是否影响基础教育资源配置",
            "concepts": ["人口变化", "基础教育资源"],
            "variables": [
                {"name": "学龄人口", "aliases_zh": ["适龄人口"], "aliases_en": ["school-age population"]},
                {"name": "学校资源", "aliases_zh": ["学校数", "教师数"], "aliases_en": ["school resources"]},
            ],
            "population": "基础教育阶段",
            "geographies": ["CHN"],
            "time_range": {"start": 2015, "end": 2026},
            "literature_queries": [
                {"query": "学龄人口 基础教育资源配置", "language": "zh", "purpose": "broad"},
                {"query": "school-age population education resource allocation", "language": "en", "purpose": "broad"},
            ],
            "data_requirements": [
                {"concept": "school-age population", "unit_hint": "people", "required": True},
                {"concept": "number of schools", "unit_hint": "count", "required": True},
            ],
        }


def test_planner_returns_bilingual_bounded_plan():
    plan = ResearchPlanner(FakeProvider()).plan("人口变化对基础教育资源配置的影响")
    assert {query.language for query in plan.literature_queries} == {"zh", "en"}
    assert len(plan.literature_queries) <= 8
    assert plan.data_requirements[0].required is True
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_planning.py -q`  
Expected: FAIL，提示 `ResearchPlanner` 不存在。

- [ ] **Step 3: 实现 planner**

`ResearchPlanner.plan(idea_text)` 使用 generation 角色和 JSON Schema 约束；在返回后执行：查询最多 8 条、每种语言至少一条、年份范围合法、重复查询标准化去重。没有 Qwen Provider 时使用现有规则生成一条中文和一条英文查询，保证离线演示可运行。

系统提示词明确：只输出计划、不声称已经检索、不生成代码、不猜测数据集 ID。

- [ ] **Step 4: 将现有 Idea 解析复用 ResearchPlan**

`run_idea_parse` 接受可选 `research_plan`；存在时把 `problem_statement、variables、population` 写入 `project.research_problem`，不再重复调用模型。

- [ ] **Step 5: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_planning.py tests\test_projects_api.py -q`  
Expected: PASS。

```bash
git add backend/edusci/autonomy/planning.py backend/edusci/services/projects.py backend/tests/test_autonomy_planning.py
git commit -m "feat: add structured autonomous research planner"
```

---

### Task 3: LiteratureScout 多轮文献发现与可信排序

**Files:**
- Create: `backend/edusci/autonomy/literature.py`
- Modify: `backend/edusci/integrations/retrieval.py`
- Modify: `backend/edusci/api/schemas.py`
- Test: `backend/tests/test_literature_scout.py`
- Test: `backend/tests/test_retrieval.py`

- [ ] **Step 1: 写失败测试，覆盖去重、排序和停止条件**

```python
from edusci.autonomy.contracts import LiteratureQuery
from edusci.autonomy.literature import LiteratureScout


class FakeLiteratureAdapter:
    name = "fake"
    def search(self, query, limit):
        return [
            {"title": "School population and resources", "doi": "10.1/a", "abstract": "Population predicts resource demand.", "year": 2024, "url": "https://doi.org/10.1/a", "citation_count": 20},
            {"title": "School population and resources", "doi": "10.1/A", "abstract": "Duplicate.", "year": 2024, "url": "https://doi.org/10.1/a", "citation_count": 20},
        ]


def test_scout_deduplicates_doi_and_records_attempts():
    scout = LiteratureScout([FakeLiteratureAdapter()], max_rounds=3)
    result = scout.discover(
        [LiteratureQuery(query="school population resources", language="en", purpose="broad")],
        concepts=["population", "resources"],
    )
    assert len(result.candidates) == 1
    assert result.candidates[0].doi == "10.1/a"
    assert result.candidates[0].relevance_score >= 70
    assert result.attempts[0].source == "fake"
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_literature_scout.py -q`  
Expected: FAIL，提示 `LiteratureScout` 不存在。

- [ ] **Step 3: 把现有检索器拆为标准适配器**

保留 `OpenResearchRetriever.search()` 兼容接口；新增 `CrossrefLiteratureAdapter` 和 `SemanticScholarLiteratureAdapter`。标准返回 DOI、标题、摘要、作者、年份、URL、许可、引用数、来源名和原始 ID。Semantic Scholar 查询字段加入 `externalIds,authors,citationCount,fieldsOfStudy,publicationDate`，并提供 `related(paper_id, limit)` 进行第三轮扩展。

- [ ] **Step 4: 实现三轮 Scout**

`LiteratureScout.discover()`：逐查询调用适配器，记录 `SearchAttemptData`；DOI 小写去重，无 DOI 使用 `normalize(title)+year`；相关性按概念命中、摘要完整性、URL/DOI、年份和类型覆盖计算。只有摘要长度至少 40 且 URL/DOI 可定位的候选转换为 PASS EvidenceCard 输入。

连续两轮无新增 PASS 或已得到 6 条且覆盖至少三类证据时停止。

- [ ] **Step 5: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_literature_scout.py tests\test_retrieval.py -q`  
Expected: PASS。

```bash
git add backend/edusci/autonomy/literature.py backend/edusci/integrations/retrieval.py backend/edusci/api/schemas.py backend/tests/test_literature_scout.py backend/tests/test_retrieval.py
git commit -m "feat: add multi-round literature scout"
```

---

### Task 4: 官方教育数据适配器

**Files:**
- Create: `backend/edusci/integrations/datasets/__init__.py`
- Create: `backend/edusci/integrations/datasets/base.py`
- Create: `backend/edusci/integrations/datasets/world_bank.py`
- Create: `backend/edusci/integrations/datasets/unicef.py`
- Create: `backend/edusci/integrations/datasets/unesco.py`
- Create: `backend/edusci/integrations/datasets/moe.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_dataset_adapters.py`

- [ ] **Step 1: 写四个失败的契约测试**

使用 `httpx.MockTransport` 分别返回官方 API 的最小 JSON/HTML 样本。测试模块先定义统一需求和按 URL 返回样本的 client：

```python
import httpx

from edusci.autonomy.contracts import DataRequirement


requirement = DataRequirement(
    concept="school-age population",
    unit_hint="people",
    required=True,
)


def client_with(routes: dict[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, payload in routes.items():
            if fragment in str(request.url):
                if isinstance(payload, str):
                    return httpx.Response(200, text=payload, request=request)
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def assert_candidate(candidate, source):
    assert candidate.source == source
    assert candidate.dataset_id
    assert candidate.title
    assert candidate.provenance_url.startswith("https://")
    assert candidate.license_status in {"allowed", "review"}


def test_world_bank_search_maps_indicator():
    client = client_with({"/indicator": [{"page": 1}, [{"id": "SP.POP.TOTL", "name": "Population, total", "sourceNote": "Population", "unit": "people"}]]})
    candidate = WorldBankAdapter(client).search(requirement, limit=5)[0]
    assert_candidate(candidate, "world_bank")
    assert candidate.unit == "people"


def test_unicef_search_maps_sdmx_flow():
    payload = {"structure": {"dataflows": [{"id": "EDUCATION", "agencyID": "UNICEF", "name": "Education access"}]}}
    assert_candidate(UnicefSdmxAdapter(client_with({"dataflow": payload})).search(requirement, 5)[0], "unicef")


def test_unesco_search_maps_indicator_definition():
    payload = [{"id": "X_SCHOOL_AGE_POP", "name": "School age population", "unit": "people"}]
    assert_candidate(UnescoUisAdapter(client_with({"definitions/indicators": payload})).search(requirement, 5)[0], "unesco_uis")


def test_moe_search_keeps_page_provenance():
    html = '<html><a href="/jyb_sjzl/moe_560/2024/gedi.html">各地学校数</a></html>'
    assert_candidate(MoeStatisticsAdapter(client_with({"moe_560": html})).search(requirement, 5)[0], "moe")
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_dataset_adapters.py -q`  
Expected: FAIL，提示 datasets 适配器包不存在。

- [ ] **Step 3: 实现基类和网络策略**

`DatasetSourceAdapter` 协议公开 `search(requirement, limit)` 与 `download(candidate, geography, years)`。`RetryingDatasetAdapter` 只允许 HTTPS，429/5xx/网络错误指数退避三次，响应体上限 50 MB，并拒绝不在适配器 `allowed_hosts` 内的重定向。

- [ ] **Step 4: 实现四个适配器**

- World Bank：`https://api.worldbank.org/v2/indicator` 发现指标，`/v2/country/{geo}/indicator/{id}?format=json&date={start}:{end}&per_page=20000` 下载。
- UNICEF：读取 `https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/dataflow/all/all/latest/?format=sdmx-json&detail=full&references=none`；只选择 UNICEF 正式 dataflow，使用 SDMX JSON/CSV 数据端点下载。
- UNESCO UIS：读取 `https://api.uis.unesco.org/api/public/definitions/indicators` 和 `.../data/indicators`；保存 UIS 署名要求和 API URL。
- 教育部：从 `https://www.moe.gov.cn/jyb_sjzl/moe_560/` 及年度页面提取同域统计表链接；HTML 表格转 CSV 时保留页面标题、URL、抓取时间和响应哈希，无法形成结构化表时只返回 `license_status="review"` 候选。

依赖增加 `beautifulsoup4>=4.12,<5` 和 `lxml>=5,<7`。

- [ ] **Step 5: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_dataset_adapters.py -q`  
Expected: PASS。

```bash
git add backend/edusci/integrations/datasets backend/pyproject.toml backend/tests/test_dataset_adapters.py
git commit -m "feat: add official education dataset adapters"
```

---

### Task 5: DataScout 候选评分、选择、下载和来源链

**Files:**
- Create: `backend/edusci/autonomy/data_scout.py`
- Modify: `backend/edusci/analysis/storage.py`
- Test: `backend/tests/test_data_scout.py`

- [ ] **Step 1: 写失败测试**

```python
from edusci.analysis.storage import LocalObjectStore
from edusci.autonomy.data_scout import DataScout
from tests.autonomy_fakes import FakeDatasetAdapter, make_dataset_candidate, make_research_plan


def test_data_scout_selects_only_traceable_allowed_candidate(tmp_path):
    plan = make_research_plan()
    allowed_candidate = make_dataset_candidate()
    unlicensed_candidate = make_dataset_candidate(
        dataset_id="blocked",
        license_status="blocked",
        license_name="All rights reserved",
        score=100,
    )
    scout = DataScout(
        adapters=[FakeDatasetAdapter(
            [allowed_candidate, unlicensed_candidate],
            b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
        )],
        store=LocalObjectStore(tmp_path),
    )
    result = scout.discover_and_select(plan, project_id="p1")
    assert result.selected.dataset_id == allowed_candidate.dataset_id
    assert result.selected.score >= 70
    assert result.asset.content_hash
    assert result.asset.row_count > 0
    assert result.provenance.transformations == ["source_json_to_tabular"]


def test_data_scout_returns_no_selection_when_variable_coverage_is_low(tmp_path):
    plan = make_research_plan()
    low_coverage = make_dataset_candidate(variable_coverage=40)
    adapter = FakeDatasetAdapter([low_coverage], b"country,year,value\nCHN,2024,100\n")
    result = DataScout([adapter], LocalObjectStore(tmp_path)).discover_and_select(plan, "p1")
    assert result.selected is None
    assert result.candidates[0].excluded_reason == "variable_coverage_below_70"
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_data_scout.py -q`  
Expected: FAIL，提示 `DataScout` 不存在。

- [ ] **Step 3: 实现评分**

标准化 0–100 分：变量覆盖 35、地区/时间覆盖 25、官方来源 15、字段/单位 15、缺失率预估 10。`license_status != allowed`、非 HTTPS、超过 50 MB 或变量覆盖低于 70% 直接排除自动选择。

- [ ] **Step 4: 实现安全下载与资产保存**

`LocalObjectStore.save_remote_dataset()` 只接受 `.csv/.json/.xlsx`，使用 UUID 文件名，计算 SHA-256。DataScout 下载最高分候选后读为 DataFrame，调用现有 `profile_dataframe`，PII 列非空则返回 `paused_risk` 而不是资产。

- [ ] **Step 5: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_data_scout.py tests\test_analysis.py -q`  
Expected: PASS。

```bash
git add backend/edusci/autonomy/data_scout.py backend/edusci/analysis/storage.py backend/tests/test_data_scout.py
git commit -m "feat: add traceable public data discovery"
```

---

### Task 6: 检查点与 AutonomousOrchestrator 到路径门禁

**Files:**
- Create: `backend/edusci/autonomy/checkpoints.py`
- Create: `backend/edusci/autonomy/orchestrator.py`
- Create: `backend/edusci/services/autonomy.py`
- Test: `backend/tests/test_autonomous_orchestrator.py`

- [ ] **Step 1: 写失败测试，证明一键运行和幂等**

```python
from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import ProjectCreate
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.database import build_session_factory
from edusci.services.projects import create_project
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    FakeProvider,
    make_dataset_candidate,
    make_research_plan,
)


def test_orchestrator_runs_to_human_gate_and_reuses_checkpoints(tmp_path):
    factory = build_session_factory(f"sqlite+pysqlite:///{(tmp_path / 'auto.db').as_posix()}")
    session = factory()
    project = create_project(session, ProjectCreate(title="资源", idea_text="人口变化对基础教育资源配置的影响"))
    literature_adapter = FakeLiteratureAdapter([
        {
            "title": f"Population and school resources {index}",
            "doi": f"10.1/resource-{index}",
            "abstract": "School-age population predicts demand for schools and teachers in education systems.",
            "year": 2024,
            "url": f"https://doi.org/10.1/resource-{index}",
            "citation_count": 10,
        }
        for index in range(6)
    ])
    dataset_adapter = FakeDatasetAdapter(
        [make_dataset_candidate()],
        b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
    )
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=LocalObjectStore(tmp_path / "files"),
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout([literature_adapter]),
        data_scout=DataScout([dataset_adapter], LocalObjectStore(tmp_path / "files")),
    )

    run = orchestrator.start(project)
    assert run.status == "awaiting_route_confirmation"
    assert project.stage == "S2_GATE"
    assert project.suggested_route == "A"
    assert literature_adapter.calls > 0
    assert dataset_adapter.calls > 0

    first_calls = (literature_adapter.calls, dataset_adapter.calls)
    orchestrator.resume(run.id)
    assert (literature_adapter.calls, dataset_adapter.calls) == first_calls
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomous_orchestrator.py -q`  
Expected: FAIL，提示 orchestrator 不存在。

- [ ] **Step 3: 实现 CheckpointStore**

`input_hash(node_name, payload)` 使用 canonical JSON + SHA-256。`run_node()` 查询完成检查点；存在则返回输出，否则写 running、执行 callable、写 completed；异常写 failed 和结构化错误。每次状态变化写 `FlowEvent`，payload 包含 `run_id、node、message、progress、timestamp`。

- [ ] **Step 4: 实现到门禁的编排**

`start(project)` 顺序执行：planning → idea_parse → literature → data_discovery → evidence_persist → gate。LiteratureScout 输出转换为 `SourceInput(verified=True)` 后复用 `run_evidence_build`。数据候选和资产写入新表。路径计算增加 `has_usable_dataset`：只有数据可用且信息/可研究性高才建议 A，否则高可研究性建议 B。

到 S2 后写 `awaiting_route_confirmation` 并正常返回，不把暂停当失败。

- [ ] **Step 5: 实现取消检查并跑绿**

每个节点前读取 `cancel_requested`；命中则设 `canceled` 并停止。运行：

`cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomous_orchestrator.py tests\test_flow.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/edusci/autonomy/checkpoints.py backend/edusci/autonomy/orchestrator.py backend/edusci/services/autonomy.py backend/tests/test_autonomous_orchestrator.py backend/edusci/services/projects.py
git commit -m "feat: orchestrate autonomous research to human gate"
```

---

### Task 7: 路径确认后的自动恢复

**Files:**
- Modify: `backend/edusci/autonomy/orchestrator.py`
- Modify: `backend/edusci/services/study.py`
- Modify: `backend/edusci/services/analysis.py`
- Modify: `backend/edusci/services/reporting.py`
- Test: `backend/tests/test_autonomous_routes.py`

- [ ] **Step 1: 写四路径失败测试**

```python
from dataclasses import dataclass

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import ProjectCreate
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.database import build_session_factory
from edusci.services.projects import confirm_route, create_project
from tests.autonomy_fakes import FakeDatasetAdapter, FakeLiteratureAdapter, FakeProvider, make_dataset_candidate, make_research_plan


@dataclass
class RoutedContext:
    session: object
    project: object
    orchestrator: AutonomousOrchestrator
    run_id: str

    def confirm_and_resume(self, route: str):
        confirm_route(self.session, self.project, route)
        return self.orchestrator.resume(self.run_id)


def build_routed_context(root) -> RoutedContext:
    factory = build_session_factory(f"sqlite+pysqlite:///{(root / 'route.db').as_posix()}")
    session = factory()
    project = create_project(session, ProjectCreate(title="自动路径", idea_text="人口变化对教育资源的影响"))
    papers = [
        {
            "title": f"Education evidence {index}",
            "doi": f"10.1/e-{index}",
            "abstract": "Population and education resources have a measurable relationship in official data.",
            "year": 2024,
            "url": f"https://doi.org/10.1/e-{index}",
            "citation_count": 5,
        }
        for index in range(6)
    ]
    store = LocalObjectStore(root / "files")
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout([FakeLiteratureAdapter(papers)]),
        data_scout=DataScout(
            [FakeDatasetAdapter([make_dataset_candidate()], b"group,outcome\nA,1\nA,2\nB,4\nB,5\n")],
            store,
        ),
    )
    run = orchestrator.start(project)
    return RoutedContext(session, project, orchestrator, run.id)


@pytest.mark.parametrize(
    ("route", "expected_status", "expected_stage", "result_kind"),
    [
        ("A", "completed", "COMPLETED", "observed"),
        ("B", "awaiting_real_data", "WAITING_FOR_DATA", None),
        ("C", "completed", "COMPLETED", "expected_only"),
        ("D", "completed", "BLOCKED", "expected_only"),
    ],
)
def test_resume_follows_confirmed_route(tmp_path, route, expected_status, expected_stage, result_kind):
    routed_context = build_routed_context(tmp_path / route)
    run = routed_context.confirm_and_resume(route)
    assert run.status == expected_status
    assert routed_context.project.stage == expected_stage
    if result_kind:
        assert routed_context.project.report["result_kind"] == result_kind
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomous_routes.py -q`  
Expected: FAIL，当前 orchestrator 不支持门禁后恢复。

- [ ] **Step 3: 实现 A/C/D 自动完成**

A 从 `DatasetAssetRecord` 创建 `DatasetRecord`，根据 `ResearchPlan` 和候选变量映射生成白名单 `AnalysisRunRequest`，调用受控分析；随后 report 和 review。C/D 跳过分析直接 study design → report → review。每个服务调用都包在 CheckpointStore 中，保证重试不重复分析。

- [ ] **Step 4: 实现 B 暂停与数据上传后恢复**

B 生成问卷后设 `awaiting_real_data`。`save_dataset` 成功后查找该项目的活动 AutonomousRun，调用 `resume_after_real_data(run_id, dataset_id)`，执行分析、报告和复审。

- [ ] **Step 5: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomous_routes.py tests\test_analysis.py tests\test_reporting.py -q`  
Expected: PASS。

```bash
git add backend/edusci/autonomy/orchestrator.py backend/edusci/services/study.py backend/edusci/services/analysis.py backend/edusci/services/reporting.py backend/tests/test_autonomous_routes.py
git commit -m "feat: resume autonomous workflow across all routes"
```

---

### Task 8: FastAPI、SSE、取消、恢复和 RQ

**Files:**
- Modify: `backend/edusci/api/routes.py`
- Modify: `backend/edusci/api/schemas.py`
- Modify: `backend/edusci/app.py`
- Modify: `backend/edusci/tasks/jobs.py`
- Modify: `backend/edusci/tasks/dispatcher.py`
- Test: `backend/tests/test_autonomy_api.py`
- Test: `backend/tests/test_autonomy_rq.py`

- [ ] **Step 1: 写 API 失败测试**

```python
def test_autonomous_run_api_reaches_gate(client):
    project_id = create_project(client)
    response = client.post(f"/api/v1/projects/{project_id}/autonomous-runs", json={})
    assert response.status_code == 202
    ref = response.json()
    assert ref["run_id"]
    run = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}").json()
    assert run["status"] == "awaiting_route_confirmation"
    events = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}/events")
    assert "event: planning" in events.text
    assert "event: awaiting_route_confirmation" in events.text


def test_cancel_and_resume_api(client):
    run_id = create_started_run(client)
    assert client.post(f"/api/v1/autonomous-runs/{run_id}/cancel").status_code == 200
    assert client.post(f"/api/v1/autonomous-runs/{run_id}/resume").status_code == 202
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_api.py -q`  
Expected: FAIL，路由 404。

- [ ] **Step 3: 实现六个接口**

按设计文档第 12 节实现 POST start、GET run、GET events、POST cancel、POST resume、GET dataset candidates。start/cancel/resume 使用 `AutonomousRunRef`；SSE 从 run 关联的 FlowEvent 输出。

- [ ] **Step 4: 注入适配器注册表**

`create_app()` 新增可选 `literature_adapters、dataset_adapters` 便于测试；生产默认注册 Crossref、Semantic Scholar、World Bank、UNICEF、UNESCO、教育部。适配器共享 httpx client 和配置超时。

- [ ] **Step 5: 实现 RQ job**

新增任务 kind `autonomous_start` 与 `autonomous_resume`。RQ payload 只保存 `run_id`；worker 重建 Session、Provider、适配器和 ObjectStore 后调用同一 `AutonomousOrchestrator`。FakeQueue 测试先断言 queued，再直接执行捕获的 job，最终状态与 inline 一致。

- [ ] **Step 6: 跑绿并提交**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_api.py tests\test_autonomy_rq.py tests\test_projects_api.py -q`  
Expected: PASS。

```bash
git add backend/edusci/api backend/edusci/app.py backend/edusci/tasks backend/tests/test_autonomy_api.py backend/tests/test_autonomy_rq.py
git commit -m "feat: expose autonomous workflow API and RQ jobs"
```

---

### Task 9: 前端自动研究时间线与数据候选

**Files:**
- Create: `frontend/src/components/AutonomousRunPanel.tsx`
- Create: `frontend/src/components/AutonomousRunPanel.test.tsx`
- Create: `frontend/src/components/DatasetCandidatesPanel.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/WorkspacePage.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: 写失败组件测试**

```tsx
it('starts autonomous research and shows gate pause', async () => {
  render(<AutonomousRunPanel projectId="p1" run={null} onChanged={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '启动自动研究' }))
  expect(await screen.findByText('正在自动检索文献与数据')).toBeVisible()
})


it('shows candidate provenance and exclusion reason', () => {
  render(<DatasetCandidatesPanel candidates={[candidate]} />)
  expect(screen.getByText('World Bank')).toBeVisible()
  expect(screen.getByText(/变量覆盖/)).toBeVisible()
})
```

- [ ] **Step 2: 运行 RED**

Run: `cd frontend && npm test -- --run src/components/AutonomousRunPanel.test.tsx`  
Expected: FAIL，组件不存在。

- [ ] **Step 3: 实现 API 与类型**

增加 `AutonomousRun、AutonomousStatus、AutonomousEvent、DatasetCandidate` 类型；API 增加 start/get/cancel/resume/list candidates。SSE 不可用时每 1 秒轮询 run 状态，终态或暂停态停止轮询。

- [ ] **Step 4: 实现面板并接入 Workspace**

S0 显示“启动自动研究”；运行中显示 planning、文献、数据、校验、门禁、分析、报告、复审节点及进度。到路径门禁复用现有 GatePanel；确认后调用现有 route confirmation，再 resume 自动运行。数据候选面板展示来源、许可、覆盖、分数、映射和排除原因。

- [ ] **Step 5: 跑绿、构建并提交**

Run: `cd frontend && npm test -- --run && npm run build`  
Expected: 所有 Vitest PASS，Vite build exit 0。

```bash
git add frontend/src
git commit -m "feat: add autonomous research progress workspace"
```

---

### Task 10: 四路径端到端、降级恢复和文档

**Files:**
- Create: `backend/tests/test_autonomy_e2e.py`
- Modify: `frontend/e2e/smoke.spec.ts`
- Modify: `scripts/e2e.ps1`
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: 写后端端到端测试**

使用 Fake Qwen、Fake LiteratureAdapter 和四个 Fake DatasetAdapter，覆盖：A 自动分析完成；B 等待数据再恢复；C 无统计；D 探索性阻断；Crossref 失败时 Semantic Scholar 降级；取消后恢复不重复调用已完成适配器。

核心断言：

```python
assert route_a.report["result_kind"] == "observed"
assert route_b_run.status == "awaiting_real_data"
assert route_c.analysis_result == {}
assert route_d.review["overall"] in {"WARN", "BLOCK"}
assert recovered.checkpoint_reuse_count > 0
assert all(reference["evidence_id"] for reference in completed.report["references"])
```

- [ ] **Step 2: 运行完整后端自动流程验收**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest tests\test_autonomy_e2e.py -q`  
Expected: 6 个验收场景全部 PASS。若任一断言失败，先按 `superpowers:systematic-debugging` 定位根因，再为根因补一个更小的失败测试，修复后重新运行本文件。

- [ ] **Step 3: 扩展 Playwright 流程**

浏览器测试创建项目、点击启动自动研究、观察节点时间线、到路径门禁确认、检查页面自动进入后续状态。使用测试后端适配器或演示种子，禁止依赖实时外部 API。

- [ ] **Step 4: 更新配置与使用文档**

`.env.example` 增加：

```dotenv
AUTONOMOUS_RESEARCH_ENABLED=true
SEMANTIC_SCHOLAR_API_KEY=
AUTONOMOUS_MAX_LITERATURE_ROUNDS=3
AUTONOMOUS_MAX_RESULTS_PER_QUERY=10
AUTONOMOUS_DOWNLOAD_LIMIT_MB=50
```

README 说明一键启动、Human Gate、来源白名单、API Key、任务恢复和测试方法。

- [ ] **Step 5: 全量验证**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\e2e.ps1
```

Expected:

- 后端所有单元、API、自动流程测试通过。
- 前端 Vitest 与生产构建通过。
- 四路径和浏览器 E2E 通过。
- 测试结束后 8000/5173 端口释放。

- [ ] **Step 6: 提交**

```bash
git add backend/tests/test_autonomy_e2e.py frontend/e2e/smoke.spec.ts scripts/e2e.ps1 README.md .env.example
git commit -m "test: verify autonomous research end to end"
```

---

## 完成审计

实现完成后逐项提供证据：

1. `AutonomousRun` 从 Idea 运行到路径门禁。
2. 文献有多轮查询、DOI 去重、排序、停止条件和失败降级。
3. World Bank、UNICEF、UNESCO、教育部四个适配器各有契约测试。
4. 数据候选有许可、来源、哈希、变量映射和质量分数。
5. A/B/C/D 四路径按确认结果自动恢复。
6. B 不伪造调查数据，A 只分析可追溯官方数据。
7. 检查点证明取消/恢复不重复执行完成节点。
8. inline 与 RQ 行为一致。
9. 前端真实显示自动节点、数据候选和暂停原因。
10. 全量测试、构建和浏览器 E2E 均为最新一次成功输出。

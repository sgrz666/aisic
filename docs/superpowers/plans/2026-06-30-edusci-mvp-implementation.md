# 教育智研 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可本地运行、可演示四路径科研流程、支持数据分析和 DOCX 导出的教育学 AI Scientist MVP。

**Architecture:** 使用 React/Ant Design 工作台和 FastAPI 模块化单体；EduSciFlow 负责状态机与人工门控，EduSciDAG 运行固定 YAML 模板，EduSciMem 通过 SQLAlchemy/pgvector 保存项目和证据。默认开发模式允许 SQLite 与内联任务，Docker Compose 切换 PostgreSQL、Redis/RQ，避免本机缺少 Docker 时无法体验。

**Tech Stack:** React、TypeScript、Vite、Ant Design、FastAPI、SQLAlchemy、PostgreSQL/pgvector、Redis/RQ、pandas/scipy/statsmodels、python-docx、pytest、Vitest、Playwright。

---

### Task 1: 工程与契约骨架

**Files:** `backend/pyproject.toml`、`frontend/package.json`、`compose.yaml`、`.env.example`

- [ ] 创建后端与前端依赖清单。
- [ ] 建立 FastAPI 应用工厂和 React 入口。
- [ ] 提供 SQLite/内联任务开发默认值以及 PostgreSQL/RQ 容器配置。
- [ ] 验证后端 `/health` 与前端构建。

### Task 2: EduSciFlow 与 EduSciDAG

**Files:** `backend/tests/test_flow.py`、`backend/edusci/domain/flow.py`、`backend/edusci/dag/`

- [ ] 先编写四象限路由、状态转换、DAG 拓扑执行的失败测试。
- [ ] 运行测试并确认因实现缺失而失败。
- [ ] 实现 70 分阈值、S0-S6 状态、节点幂等与三个 YAML 模板。
- [ ] 运行测试并确认通过。

### Task 3: EduSciMem 与项目 API

**Files:** `backend/tests/test_projects_api.py`、`backend/edusci/memory/`、`backend/edusci/api/`

- [ ] 先编写项目创建、Idea 解析、证据构建、门控确认的 API 测试。
- [ ] 实现 SQLAlchemy 模型、仓储、Trust Guard 和对应 API。
- [ ] 确保每条 EvidenceCard 包含来源定位、内容哈希与核验状态。
- [ ] 验证 OpenAPI 和项目阶段快照。

### Task 4: 研究设计与受控统计

**Files:** `backend/tests/test_analysis.py`、`backend/edusci/analysis/`、`backend/edusci/research_design/`

- [ ] 先编写问卷结构、CSV 质量报告和描述/差异/相关分析测试。
- [ ] 实现白名单统计函数，禁止执行生成代码。
- [ ] 实现路径 B 问卷、变量题项映射、编码字典和等待上传状态。
- [ ] 验证缺失值、异常值和不支持文件错误。

### Task 5: 报告、复审与任务事件

**Files:** `backend/tests/test_reporting.py`、`backend/edusci/reporting/`、`backend/edusci/tasks/`

- [ ] 先编写无真实数据不产生统计结论、BLOCK 禁止最终导出的测试。
- [ ] 实现标准研究计划、CitationMap、四类审查和最多两轮修订契约。
- [ ] 实现 TaskRef、SSE 事件、取消和失败节点重试。
- [ ] 实现 DOCX 导出并验证文件可打开。

### Task 6: React 科研工作台

**Files:** `frontend/src/`、`frontend/src/**/*.test.tsx`

- [ ] 先编写项目创建、阶段导航和路径确认的组件测试。
- [ ] 实现项目首页、科研工作台、证据卡、门控面板、问卷编辑、数据上传、报告与风险抽屉。
- [ ] 使用暖白纸张、墨蓝、朱砂强调色和中文研究档案视觉语言。
- [ ] 验证响应式布局、键盘操作和空/错/加载状态。

### Task 7: 演示、运维与验收

**Files:** `Makefile`、`scripts/`、`README.md`、`backend/tests/test_e2e_routes.py`

- [ ] 提供 `make dev/test/e2e/demo-seed` 和对应 PowerShell 脚本。
- [ ] 写入 A/B/C/D 四路径种子项目。
- [ ] 运行后端 pytest、前端 Vitest/build、API 端到端测试。
- [ ] 启动开发服务器并完成浏览器视觉与交互验证。


import {
  ArrowLeftOutlined,
  CloudUploadOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Alert, Button, Input, Result, Skeleton, Space, Statistic, Upload, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  confirmRoute,
  getAutonomousRun,
  getProject,
  listEvidence,
  runAnalysis,
  runEvidence,
  runGate,
  runIdeaParse,
  runReport,
  runReview,
  runStudyDesign,
  resumeAutonomousRun,
  uploadDataset,
  uploadDocument,
} from '../api'
import { BrandMark } from '../components/BrandMark'
import { AutonomousRunPanel } from '../components/AutonomousRunPanel'
import { EvidenceDrawer } from '../components/EvidenceDrawer'
import { GatePanel } from '../components/GatePanel'
import { QuestionnairePanel } from '../components/QuestionnairePanel'
import { ReportPanel } from '../components/ReportPanel'
import { StageRail } from '../components/StageRail'
import type {
  AutonomousRun,
  EvidenceCard,
  Project,
  ResearchRoute,
  ResearchScores,
} from '../types'

export function WorkspacePage() {
  const { projectId = '' } = useParams()
  const [projectState, setProject] = useState<Project | null>(null)
  const [evidence, setEvidence] = useState<EvidenceCard[]>([])
  const [drawer, setDrawer] = useState(false)
  const [busy, setBusy] = useState(false)
  const [autonomousRun, setAutonomousRun] = useState<AutonomousRun | null>(null)
  const [analysisColumns, setAnalysisColumns] = useState({ outcome: 'AI焦虑得分', group: '专业' })

  const refresh = useCallback(async () => {
    const [projectData, cards] = await Promise.all([
      getProject(projectId),
      listEvidence(projectId).catch(() => []),
    ])
    setProject(projectData)
    setEvidence(cards)
  }, [projectId])

  useEffect(() => { refresh().catch((error) => message.error(error.message)) }, [refresh])

  const handleAutonomousChanged = useCallback((latest: AutonomousRun) => {
    setAutonomousRun(latest)
    refresh().catch((error) => message.error(error.message))
  }, [refresh])

  async function action(operation: () => Promise<unknown>) {
    setBusy(true)
    try { await operation(); await refresh() }
    catch (error) { message.error(error instanceof Error ? error.message : '操作失败') }
    finally { setBusy(false) }
  }

  if (!projectState) return <div className="workspace-loading"><Skeleton active paragraph={{ rows: 8 }} /></div>

  const project = projectState

  const scores = project.scores as Partial<ResearchScores>
  const questionnaire = project.study_design?.questionnaire

  async function finishEvidence() {
    await runEvidence(project.id)
    await runGate(project.id)
  }

  async function analyzeFile(file: File) {
    const dataset = await uploadDataset(project.id, file)
    if (autonomousRun?.status === 'awaiting_real_data') {
      const latest = await getAutonomousRun(autonomousRun.id)
      setAutonomousRun(latest)
      await refresh()
      return false
    }
    await runAnalysis(project.id, {
      dataset_id: dataset.id,
      outcome_column: analysisColumns.outcome,
      group_column: analysisColumns.group,
    })
    await refresh()
    return false
  }

  async function confirmAndContinue(route: ResearchRoute) {
    await confirmRoute(project.id, route)
    if (autonomousRun?.status === 'awaiting_route_confirmation') {
      await resumeAutonomousRun(autonomousRun.id)
      const latest = await getAutonomousRun(autonomousRun.id)
      setAutonomousRun(latest)
    }
  }

  function dataUploadPanel(mode: 'collected' | 'existing') {
    const isCollected = mode === 'collected'
    return (
      <section className="paper-panel data-upload-panel">
        <div>
          <div className="section-kicker">{isCollected ? 'HUMAN IN THE LOOP' : 'CONTROLLED ANALYSIS'}</div>
          <h2>{isCollected ? '回传真实数据' : '导入已有开放数据'}</h2>
          <p>{isCollected
            ? '在外部完成问卷发放后，上传 CSV/XLSX。系统不会自动伪造答卷。'
            : '上传与研究设计匹配的 CSV/XLSX，统计计算只调用受控函数，不执行模型生成代码。'}</p>
        </div>
        <Space direction="vertical" size="middle">
          <Input addonBefore="结果变量" value={analysisColumns.outcome} onChange={(event) => setAnalysisColumns((current) => ({ ...current, outcome: event.target.value }))} />
          <Input addonBefore="分组变量" value={analysisColumns.group} onChange={(event) => setAnalysisColumns((current) => ({ ...current, group: event.target.value }))} />
          <Upload accept=".csv,.xlsx" maxCount={1} showUploadList={false} beforeUpload={(file) => { setBusy(true); analyzeFile(file).catch((error) => message.error(error.message)).finally(() => setBusy(false)); return false }}>
            <Button type="primary" loading={busy} icon={<CloudUploadOutlined />}>上传并运行受控分析</Button>
          </Upload>
        </Space>
      </section>
    )
  }

  function renderStage() {
    switch (project.stage) {
      case 'S0_IDEA':
        return <IntroPanel project={project} busy={busy} onRun={() => action(() => runIdeaParse(project.id))} />
      case 'S1_EVIDENCE':
        return (
          <section className="paper-panel evidence-workbench">
            <div className="section-kicker">EVIDENCE FIRST</div><h2>建立可追溯证据包</h2>
            <p>上传种子论文，或启用开放检索适配器。每条事实都保留来源定位与内容哈希。</p>
            <div className="drop-grid">
              <Upload.Dragger
                accept=".pdf"
                maxCount={1}
                showUploadList={false}
                beforeUpload={(file) => { action(() => uploadDocument(project.id, file)); return false }}
              >
                <CloudUploadOutlined /><strong>摄入 PDF 文献</strong><small>最大 50 MB · 按页切分</small>
              </Upload.Dragger>
              <div className="evidence-count-card"><Statistic title="当前证据卡" value={evidence.length} suffix="条" /><Button onClick={() => setDrawer(true)}>查看来源</Button></div>
            </div>
            <Button type="primary" size="large" loading={busy} icon={<SafetyCertificateOutlined />} onClick={() => action(finishEvidence)}>完成证据构建并评分</Button>
          </section>
        )
      case 'S2_GATE':
        return <GatePanel scores={{ information_sufficiency: scores.information_sufficiency ?? 0, researchability: scores.researchability ?? 0 }} suggestedRoute={(project.suggested_route ?? 'D') as ResearchRoute} loading={busy} onConfirm={(route) => action(() => confirmAndContinue(route))} />
      case 'S3_DESIGN':
        return (
          <Result
            className="paper-panel"
            icon={<FileTextOutlined />}
            title={`路径 ${project.route} 已确认`}
            subTitle="系统将生成与该路径相符的研究假设、伦理边界与实施工具。"
            extra={<Button type="primary" size="large" loading={busy} onClick={() => action(() => runStudyDesign(project.id))}>生成研究设计</Button>}
          />
        )
      case 'WAITING_FOR_DATA':
        return (
          <div className="stage-stack">
            <QuestionnairePanel questionnaire={questionnaire} />
            {dataUploadPanel('collected')}
          </div>
        )
      case 'S4_ANALYSIS':
        return dataUploadPanel('existing')
      case 'S5_REPORT':
        return <Result className="paper-panel" icon={<FileTextOutlined />} title="证据与分析已就绪" subTitle="生成统一格式的《教育学科学假设与研究计划》。" extra={<Button type="primary" loading={busy} onClick={() => action(() => runReport(project.id))}>生成研究计划</Button>} />
      case 'S6_REVIEW':
        return <Result className="paper-panel" icon={<FileSearchOutlined />} title="报告等待独立复审" subTitle="将并行检查引用、统计、逻辑与伦理边界。" extra={<Button type="primary" loading={busy} onClick={() => action(() => runReview(project.id))}>运行四类复审</Button>} />
      case 'COMPLETED':
      case 'BLOCKED':
        return <ReportPanel projectId={project.id} report={project.report} review={project.review} />
      default:
        return <Result status="warning" title={project.stage} subTitle="该阶段需要从任务记录恢复。" />
    }
  }

  return (
    <div className="workspace-page">
      <header className="workspace-header">
        <Link to="/" aria-label="返回项目列表"><ArrowLeftOutlined /></Link>
        <BrandMark compact />
        <div className="workspace-title"><span>{project.title}</span><small>{project.idea_text}</small></div>
        <Button icon={<FileSearchOutlined />} onClick={() => setDrawer(true)}>证据 {evidence.length}</Button>
        <Button icon={<ReloadOutlined />} onClick={() => refresh()}>刷新</Button>
      </header>
      <div className="workspace-grid">
        <StageRail currentStage={project.stage} />
        <main className="workspace-main">
          <div className="stage-stack">
            <AutonomousRunPanel
              projectId={project.id}
              run={autonomousRun}
              onChanged={handleAutonomousChanged}
            />
            {renderStage()}
          </div>
        </main>
      </div>
      <EvidenceDrawer open={drawer} onClose={() => setDrawer(false)} evidence={evidence} />
    </div>
  )
}

function IntroPanel({ project, busy, onRun }: { project: Project; busy: boolean; onRun: () => void }) {
  return (
    <section className="paper-panel intro-panel">
      <div className="section-kicker">IDEA INTAKE · S0</div>
      <h1>{project.idea_text}</h1>
      <div className="annotation"><span>研究者原始输入</span><p>系统会识别研究对象、核心变量、教育场景和需要澄清的边界。</p></div>
      <Alert type="info" showIcon message="系统生成的是研究辅助材料，不替代伦理审查、学校审批或真实受试者知情同意。" />
      <Button type="primary" size="large" loading={busy} onClick={onRun}>解析研究问题</Button>
    </section>
  )
}

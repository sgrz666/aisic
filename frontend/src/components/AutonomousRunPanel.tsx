import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { Alert, Button, Progress, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  cancelAutonomousRun,
  getAutonomousRun,
  getAutonomousEvidenceGraph,
  getAutonomousResearchState,
  listDatasetCandidates,
  resumeAutonomousRun,
  startAutonomousResearch,
} from '../api'
import type {
  AutonomousResearchState,
  AutonomousRun,
  AutonomousStatus,
  DatasetCandidate,
  EvidenceGraph,
} from '../types'
import { DatasetCandidatesPanel } from './DatasetCandidatesPanel'
import { EvidenceMatrixPanel } from './EvidenceMatrixPanel'
import { ResearchProgressPanel } from './ResearchProgressPanel'
import { ResearchReportEntry } from './ResearchReportEntry'

/* ── Activity log entry ── */
interface ActivityEntry {
  node: string
  message: string
  progress: number
  timestamp: string
  type: 'progress' | 'node_completed'
}

/* ── Node rail mapping: backend node name → display label ── */
const NODE_LABELS: [string, string][] = [
  ['planning', '规划'],
  ['literature', '文献'],
  ['data_discovery', '数据'],
  ['deep_research', '校验'],
  ['gate', '门禁'],
  ['analysis', '分析'],
  ['report', '报告'],
  ['review', '复审'],
]

/* All backend node names that belong to a rail label (some nodes share a label) */
const LABEL_TO_NODES: Record<string, string[]> = {
  '规划': ['planning', 'idea_parse'],
  '文献': ['literature'],
  '数据': ['data_discovery'],
  '校验': ['deep_research', 'evidence_persist'],
  '门禁': ['gate'],
  '分析': ['analysis', 'study_design', 'prepare_public_dataset'],
  '报告': ['report'],
  '复审': ['review'],
}

const activeStatuses = new Set<AutonomousStatus>([
  'queued',
  'planning',
  'searching_literature',
  'searching_datasets',
  'ranking_sources',
  'validating_evidence',
  'designing_study',
  'downloading_dataset',
  'analyzing',
  'generating_report',
  'reviewing',
])

const statusCopy: Record<AutonomousStatus, { label: string; progress: number }> = {
  queued: { label: '任务已排队，准备启动', progress: 3 },
  planning: { label: '正在理解研究问题', progress: 10 },
  searching_literature: { label: '正在自动检索文献与数据', progress: 35 },
  searching_datasets: { label: '正在寻找可信开放数据', progress: 55 },
  ranking_sources: { label: '正在比较来源质量', progress: 62 },
  validating_evidence: { label: '正在核验引用与证据', progress: 74 },
  awaiting_route_confirmation: { label: '等待你确认研究路径', progress: 85 },
  designing_study: { label: '正在生成研究设计', progress: 90 },
  downloading_dataset: { label: '正在安全下载数据', progress: 92 },
  analyzing: { label: '正在运行受控统计分析', progress: 94 },
  generating_report: { label: '正在生成研究报告', progress: 97 },
  reviewing: { label: '正在执行独立复审', progress: 99 },
  awaiting_real_data: { label: '等待上传真实问卷数据', progress: 91 },
  paused_risk: { label: '检测到风险，已安全暂停', progress: 60 },
  failed: { label: '运行失败，可从检查点恢复', progress: 0 },
  canceled: { label: '运行已取消', progress: 0 },
  completed: { label: '自治研究流程已完成', progress: 100 },
}

/* ── Helper: format elapsed seconds into human-readable ── */
function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  if (m < 60) return `${m}分${s > 0 ? s + '秒' : ''}`
  const h = Math.floor(m / 60)
  return `${h}时${m % 60}分`
}

/* ── Helper: format ISO timestamp to HH:MM:SS ── */
function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

/* ── Sub-component: Activity Timeline ── */
function ActivityTimeline({ entries }: { entries: ActivityEntry[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [entries.length])

  if (entries.length === 0) {
    return (
      <div className="activity-timeline activity-timeline--empty">
        <LoadingOutlined spin /> <span>等待研究代理启动…</span>
      </div>
    )
  }

  return (
    <div className="activity-timeline" ref={scrollRef}>
      {entries.map((entry, i) => (
        <div
          key={`${entry.node}-${entry.type}-${i}`}
          className={`timeline-entry ${entry.type === 'node_completed' ? 'timeline-entry--done' : 'timeline-entry--progress'}`}
        >
          <span className="timeline-entry__icon">
            {entry.type === 'node_completed' ? (
              <CheckCircleOutlined />
            ) : (
              <SyncOutlined spin />
            )}
          </span>
          <span className="timeline-entry__time">{formatTime(entry.timestamp)}</span>
          <span className="timeline-entry__node">{entry.node}</span>
          <span className="timeline-entry__msg">{entry.message}</span>
        </div>
      ))}
    </div>
  )
}

/* ── Main component ── */
interface AutonomousRunPanelProps {
  projectId: string
  run: AutonomousRun | null
  onChanged: (run: AutonomousRun) => void
}

export function AutonomousRunPanel({
  projectId,
  run,
  onChanged,
}: AutonomousRunPanelProps) {
  const [current, setCurrent] = useState<AutonomousRun | null>(run)
  const [candidates, setCandidates] = useState<DatasetCandidate[]>([])
  const [researchState, setResearchState] = useState<AutonomousResearchState | null>(null)
  const [evidenceGraph, setEvidenceGraph] = useState<EvidenceGraph | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [eventLog, setEventLog] = useState<ActivityEntry[]>([])
  const [elapsed, setElapsed] = useState(0)
  const startTimeRef = useRef<number | null>(null)

  useEffect(() => setCurrent(run), [run])

  /* Reset event log when a new run starts */
  useEffect(() => {
    if (current?.id) {
      setEventLog([])
      startTimeRef.current = Date.now()
      setElapsed(0)
    }
  }, [current?.id])

  /* Elapsed time ticker */
  useEffect(() => {
    if (!current || !activeStatuses.has(current.status)) return undefined
    if (!startTimeRef.current) startTimeRef.current = Date.now()
    const tick = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - (startTimeRef.current ?? Date.now())) / 1000))
    }, 1000)
    return () => window.clearInterval(tick)
  }, [current?.id, current?.status])

  /* Side-data loading: dataset candidates, research state, evidence graph */
  useEffect(() => {
    if (!current?.id) return undefined
    let canceled = false
    const load = async () => {
      const [items, state, graph] = await Promise.allSettled([
        listDatasetCandidates(current.id),
        getAutonomousResearchState(current.id),
        getAutonomousEvidenceGraph(current.id),
      ])
      if (!canceled) {
        if (items.status === 'fulfilled') setCandidates(items.value)
        if (state.status === 'fulfilled') setResearchState(state.value)
        if (graph.status === 'fulfilled') setEvidenceGraph(graph.value)
      }
    }
    load().catch(() => undefined)
    return () => { canceled = true }
  }, [current?.id, current?.status])

  /* Append a parsed SSE event to the activity log */
  const pushEvent = useCallback((data: Record<string, unknown>, type: 'progress' | 'node_completed') => {
    const entry: ActivityEntry = {
      node: String(data.node ?? ''),
      message: String(data.message ?? ''),
      progress: Number(data.progress ?? 0),
      timestamp: String(data.timestamp ?? new Date().toISOString()),
      type,
    }
    setEventLog((prev) => {
      const next = [...prev, entry]
      return next.length > 50 ? next.slice(-50) : next
    })
  }, [])

  /* SSE connection + polling fallback */
  useEffect(() => {
    if (!current || !activeStatuses.has(current.status)) return undefined
    let timer: number | undefined
    const refreshRun = async () => {
      try {
        const latest = await getAutonomousRun(current.id)
        setCurrent(latest)
        onChanged(latest)
      } catch { /* the next poll or manual retry can recover */ }
    }
    const startPolling = () => {
      if (timer === undefined) timer = window.setInterval(refreshRun, 1000)
    }
    if (typeof EventSource === 'undefined') {
      startPolling()
      return () => { if (timer !== undefined) window.clearInterval(timer) }
    }
    const source = new EventSource(`/api/v1/autonomous-runs/${current.id}/events`)

    /* Parse SSE payload and push to activity log */
    const handleEvent = (eventType: 'progress' | 'node_completed') => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        pushEvent(data, eventType)
      } catch { /* ignore parse failures */ }
      refreshRun()
    }

    source.addEventListener('progress', handleEvent('progress'))
    source.addEventListener('node_completed', handleEvent('node_completed'))

    /* Terminal / pause events – just refresh the run state */
    const terminalEvents = [
      'awaiting_route_confirmation',
      'awaiting_real_data',
      'paused_risk',
      'failed',
      'completed',
    ]
    terminalEvents.forEach((name) => source.addEventListener(name, refreshRun))

    source.onerror = () => {
      source.close()
      startPolling()
    }
    return () => {
      source.close()
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [current?.id, current?.status, onChanged, pushEvent])

  async function start() {
    setSubmitting(true)
    try {
      const ref = await startAutonomousResearch(projectId)
      const latest = await getAutonomousRun(ref.run_id)
      setCurrent(latest)
      onChanged(latest)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '自动研究启动失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function cancel() {
    if (!current) return
    setSubmitting(true)
    try {
      await cancelAutonomousRun(current.id)
      const latest = await getAutonomousRun(current.id)
      setCurrent(latest)
      onChanged(latest)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '取消失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function resume() {
    if (!current) return
    setSubmitting(true)
    try {
      await resumeAutonomousRun(current.id)
      const latest = await getAutonomousRun(current.id)
      setCurrent(latest)
      onChanged(latest)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '恢复失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (!current) {
    return (
      <section className="autonomous-panel autonomous-panel--idle">
        <div className="autonomous-panel__seal"><RobotOutlined /></div>
        <div>
          <span className="section-kicker">AUTONOMOUS RESEARCH</span>
          <h2>把检索与验证交给研究代理</h2>
          <p>系统会自主检索文献和官方数据，并在路径选择、伦理风险或真实数据门禁处停下来等你。</p>
        </div>
        <Button
          aria-label="启动自动研究"
          type="primary"
          size="large"
          icon={<PlayCircleOutlined />}
          loading={submitting}
          onClick={start}
        >
          启动自动研究
        </Button>
      </section>
    )
  }

  const copy = statusCopy[current.status]
  const isPaused = [
    'awaiting_route_confirmation',
    'awaiting_real_data',
    'paused_risk',
  ].includes(current.status)
  const canResume = ['failed', 'canceled'].includes(current.status)

  /* Determine each node-rail item's state: done / active / future */
  const completedNodes = new Set(
    eventLog.filter((e) => e.type === 'node_completed').map((e) => e.node),
  )
  const currentNode = current.current_node ?? ''

  function nodeState(label: string): 'done' | 'active' | 'future' {
    const backendNodes = LABEL_TO_NODES[label] ?? []
    if (current!.status === 'completed') return 'done'
    if (backendNodes.some((n) => n === currentNode)) return 'active'
    if (backendNodes.some((n) => completedNodes.has(n))) return 'done'
    return 'future'
  }

  return (
    <section className="autonomous-panel autonomous-panel--running" aria-live="polite">
      <div className="autonomous-panel__topline">
        <div>
          <span className="section-kicker">RESEARCH RUN · {current.id.slice(0, 8)}</span>
          <h2>{copy.label}</h2>
        </div>
        <div className="autonomous-panel__topline-right">
          {activeStatuses.has(current.status) && (
            <span className="autonomous-panel__elapsed">
              <ClockCircleOutlined /> {formatElapsed(elapsed)}
            </span>
          )}
          <Tag color={current.status === 'completed' ? 'green' : isPaused ? 'gold' : 'blue'}>
            {current.status}
          </Tag>
        </div>
      </div>
      <Progress percent={copy.progress} strokeColor="#b94d32" trailColor="#ded7c8" />
      <div className="autonomous-panel__nodes" aria-label="自动研究节点">
        {NODE_LABELS.map(([, label]) => {
          const state = nodeState(label)
          return (
            <span key={label} className={`node-${state}`}>
              {label}
            </span>
          )
        })}
      </div>

      {/* ── Activity Timeline ── */}
      <div className="autonomous-panel__timeline-wrapper">
        <div className="autonomous-panel__timeline-header">
          <span className="section-kicker">
            <SyncOutlined spin={activeStatuses.has(current.status)} /> 活动日志
          </span>
          <span className="autonomous-panel__timeline-count">{eventLog.length} 条事件</span>
        </div>
        <ActivityTimeline entries={eventLog} />
      </div>

      {current.status === 'awaiting_route_confirmation' && (
        <Alert showIcon icon={<PauseCircleOutlined />} type="warning" message="路径建议已经准备好，请在下方确认后继续。" />
      )}
      {current.status === 'paused_risk' && (
        <Alert showIcon type="error" message="检测到个人信息或伦理风险，自动流程没有继续写入分析结果。" />
      )}
      {current.status === 'failed' && (
        <Alert showIcon type="error" message={String(current.error.message || '外部服务暂时不可用')} />
      )}
      <div className="autonomous-panel__actions">
        {activeStatuses.has(current.status) && (
          <Button danger icon={<CloseCircleOutlined />} loading={submitting} onClick={cancel}>取消</Button>
        )}
        {canResume && (
          <Button type="primary" icon={<ReloadOutlined />} loading={submitting} onClick={resume}>从检查点恢复</Button>
        )}
      </div>
      <Tabs
        className="research-workbench-tabs"
        items={[
          {
            key: 'progress',
            label: '研究进度',
            children: (
              <>
                <ResearchProgressPanel run={current} state={researchState} />
                <DatasetCandidatesPanel candidates={candidates} />
              </>
            ),
          },
          {
            key: 'evidence',
            label: '证据矩阵',
            children: <EvidenceMatrixPanel graph={evidenceGraph} />,
          },
          {
            key: 'report',
            label: '最终报告',
            children: <ResearchReportEntry projectId={projectId} status={current.status} />,
          },
        ]}
      />
    </section>
  )
}

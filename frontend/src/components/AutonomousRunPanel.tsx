import {
  CloseCircleOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { Alert, Button, Progress, Tag, message } from 'antd'
import { useEffect, useState } from 'react'

import {
  cancelAutonomousRun,
  getAutonomousRun,
  listDatasetCandidates,
  resumeAutonomousRun,
  startAutonomousResearch,
} from '../api'
import type { AutonomousRun, AutonomousStatus, DatasetCandidate } from '../types'
import { DatasetCandidatesPanel } from './DatasetCandidatesPanel'

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
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => setCurrent(run), [run])

  useEffect(() => {
    if (!current?.id) return undefined
    let canceled = false
    const load = async () => {
      const items = await listDatasetCandidates(current.id)
      if (!canceled) setCandidates(items)
    }
    load().catch(() => undefined)
    return () => { canceled = true }
  }, [current?.id, current?.status])

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
    const eventNames = [
      'progress',
      'node_completed',
      'awaiting_route_confirmation',
      'awaiting_real_data',
      'paused_risk',
      'failed',
      'completed',
    ]
    eventNames.forEach((eventName) => source.addEventListener(eventName, refreshRun))
    source.onerror = () => {
      source.close()
      startPolling()
    }
    return () => {
      source.close()
      if (timer !== undefined) window.clearInterval(timer)
    }
  }, [current?.id, current?.status, onChanged])

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

  return (
    <section className="autonomous-panel autonomous-panel--running" aria-live="polite">
      <div className="autonomous-panel__topline">
        <div>
          <span className="section-kicker">RESEARCH RUN · {current.id.slice(0, 8)}</span>
          <h2>{copy.label}</h2>
        </div>
        <Tag color={current.status === 'completed' ? 'green' : isPaused ? 'gold' : 'blue'}>
          {current.status}
        </Tag>
      </div>
      <Progress percent={copy.progress} strokeColor="#b94d32" trailColor="#ded7c8" />
      <div className="autonomous-panel__nodes" aria-label="自动研究节点">
        {['规划', '文献', '数据', '校验', '门禁', '分析', '报告', '复审'].map((node) => (
          <span key={node}>{node}</span>
        ))}
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
      <DatasetCandidatesPanel candidates={candidates} />
    </section>
  )
}

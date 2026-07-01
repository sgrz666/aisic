import {
  DownloadOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Alert, Button, Descriptions, Progress, Statistic, Tag, message } from 'antd'
import { useState } from 'react'

import { regenerateReport, reportDownloadUrl } from '../api'
import type { ResearchReport, ReviewResult } from '../types'

interface ReportPanelProps {
  projectId: string
  report: ResearchReport
  review: ReviewResult
  onRegenerated?: () => void | Promise<void>
}

const resultLabels: Record<string, string> = {
  observed_empirical: '真实数据实证',
  simulation_feasibility: '模拟可行性',
  expected_only: '待验证计划',
}

function text(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.map(text).join('；')
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}：${text(item)}`).join('；')
  return String(value)
}

export function ReportPanel({
  projectId,
  report,
  review,
  onRegenerated,
}: ReportPanelProps) {
  const [regenerating, setRegenerating] = useState(false)
  const blocked = review?.overall === 'BLOCK'
  const isV2 = report.schema_version === 2

  async function regenerate() {
    setRegenerating(true)
    try {
      await regenerateReport(projectId)
      await onRegenerated?.()
      message.success('V2 报告已重新生成')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '报告重新生成失败')
    } finally {
      setRegenerating(false)
    }
  }

  if (!isV2) {
    return (
      <section className="paper-panel report-panel">
        <div className="report-panel__top">
          <div><div className="section-kicker">LEGACY RESEARCH ARTIFACT</div><h2>{report.title ?? '教育学科学假设与研究计划'}</h2></div>
          <Tag color="warning">V1</Tag>
        </div>
        <Alert showIcon type="warning" message="这是旧版报告，建议重新生成 V2 以补齐技术细节、数据来源、实验指标和规范排版。" />
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="待研究问题">{report.problem}</Descriptions.Item>
          <Descriptions.Item label="解决思路">{text(report.rationale)}</Descriptions.Item>
          <Descriptions.Item label="方法论">{text(report.methods)}</Descriptions.Item>
          <Descriptions.Item label="结果边界">{text(report.results)}</Descriptions.Item>
        </Descriptions>
        <div className="report-actions"><Button type="primary" aria-label="重新生成 V2" loading={regenerating} icon={<ReloadOutlined />} onClick={regenerate}>重新生成 V2</Button></div>
      </section>
    )
  }

  const results = typeof report.results === 'object' ? report.results : {}
  const datasets = report.datasets ?? {}
  const target = datasets.target ?? {}
  const references = report.references ?? []
  const reviewChecks = review.checks ?? {}
  const problem = report.problem_statement ?? {}
  const rationale = typeof report.rationale === 'object' ? report.rationale : {}

  return (
    <section className="paper-panel report-panel report-panel--v2">
      <div className="report-panel__top">
        <div>
          <div className="section-kicker">RESEARCH ARTIFACT · V2</div>
          <h2>{report.paper_title}</h2>
          <div className="report-tags">
            {(report.keywords ?? []).map((keyword) => <Tag key={keyword}>{keyword}</Tag>)}
          </div>
        </div>
        <Tag color={blocked ? 'error' : review?.overall === 'PASS' ? 'success' : 'warning'} icon={<SafetyCertificateOutlined />}>
          {review?.overall ?? '待复审'}
        </Tag>
      </div>

      <div className="report-status-strip">
        <Statistic title="结果性质" value={resultLabels[results.kind ?? ''] ?? results.kind ?? '待判断'} />
        <Statistic title="样本量" value={results.sample_size ?? 0} />
        <Statistic title="真实 Source" value={datasets.source?.length ?? 0} />
        <Statistic title="可核验引用" value={references.length} />
      </div>

      <div className="report-abstract"><span>摘要</span><p>{report.abstract}</p></div>

      <div className="report-section-grid">
        <article className="report-section-card">
          <span className="section-kicker">PROBLEM STATEMENT</span>
          <h3>待研究问题</h3>
          <p>{problem.current_limitation}</p>
          <strong>知识缺口</strong><p>{problem.knowledge_gap}</p>
          <strong>研究问题</strong><p>{problem.research_question}</p>
        </article>
        <article className="report-section-card">
          <span className="section-kicker">RATIONALE</span>
          <h3>解决思路</h3>
          <p>{rationale.innovation}</p>
          <ol>{(rationale.reasoning_chain ?? []).map((step) => <li key={step}>{step}</li>)}</ol>
        </article>
      </div>

      <section className="report-detail-section">
        <div className="report-detail-heading"><ExperimentOutlined /><div><span className="section-kicker">TECHNICAL DETAILS</span><h3>必要的技术手段</h3></div></div>
        <div className="technical-grid">
          {(report.technical_details ?? []).map((item) => (
            <article key={`${item.purpose}-${item.method}`}>
              <Tag color={item.execution_status === 'executed' ? 'green' : 'blue'}>{item.execution_status}</Tag>
              <strong>{item.method}</strong><span>{item.purpose}</span>
              <p>{item.rationale}</p><small>{item.stack.join(' / ')}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="report-detail-section">
        <span className="section-kicker">DATASETS · SOURCE / TARGET</span><h3>数据集</h3>
        {(datasets.simulation_input?.length ?? 0) > 0 && (
          <Alert showIcon type="warning" message={`模拟输入：${datasets.simulation_input?.map((item) => text(item.name)).join('、')}`} description="模拟数据只用于验证分析流程，不进入真实 Source，也不支持现实因果结论。" />
        )}
        <div className="dataset-report-grid">
          <article><strong>Source · 合规真实数据</strong><p>{datasets.source?.length ? datasets.source.map((item) => text(item.name)).join('；') : '当前没有满足来源和许可要求的真实 Source 数据。'}</p></article>
          <article><strong>Target · 拟采集验证数据</strong><p>{text(target.population)}</p><small>特征：{text(target.features)} · 最低样本量：{text(target.minimum_sample_size)}</small></article>
        </div>
      </section>

      <section className="report-detail-section">
        <span className="section-kicker">EXPERIMENTS</span><h3>Baselines 与 Metrics</h3>
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Baselines">{text(report.experiments?.baselines)}</Descriptions.Item>
          <Descriptions.Item label="Metrics">{text(report.experiments?.metrics)}</Descriptions.Item>
          <Descriptions.Item label="验证设计">{report.experiments?.validation_design}</Descriptions.Item>
        </Descriptions>
      </section>

      <section className="report-result-callout">
        <div><span className="section-kicker">RESULTS</span><h3>{resultLabels[results.kind ?? ''] ?? '结果'}</h3></div>
        <Progress type="dashboard" percent={review?.overall === 'PASS' ? 100 : review?.overall === 'WARN' ? 70 : 35} strokeColor="#b94d32" />
        <div><strong>{results.status}</strong><p>{results.feasibility_conclusion}</p><small>{text(results.limitations)}</small></div>
      </section>

      {Object.entries(reviewChecks).map(([name, item]) => {
        const check = item as { status?: string; message?: string }
        return check.status === 'PASS' ? null : <Alert key={name} showIcon type={check.status === 'BLOCK' ? 'error' : 'warning'} message={`${name} · ${check.status}`} description={check.message} />
      })}

      <div className="report-actions">
        <Button aria-label="重新生成 V2" loading={regenerating} icon={<ReloadOutlined />} onClick={regenerate}>重新生成 V2</Button>
        <Button icon={<DownloadOutlined />} href={reportDownloadUrl(projectId, 'draft')}>下载草稿 DOCX</Button>
        <Button type="primary" disabled={blocked || !review?.overall} icon={<DownloadOutlined />} href={reportDownloadUrl(projectId, 'final')}>下载比赛报告</Button>
      </div>
    </section>
  )
}

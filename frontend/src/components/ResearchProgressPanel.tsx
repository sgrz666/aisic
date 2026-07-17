import { Progress, Statistic } from 'antd'

import type { AutonomousResearchState, AutonomousRun } from '../types'

interface ResearchProgressPanelProps {
  run: AutonomousRun
  state: AutonomousResearchState | null
}

export function ResearchProgressPanel({ run, state }: ResearchProgressPanelProps) {
  const metrics = state?.metrics ?? {
    current_iteration: run.current_iteration ?? 0,
    source_count: run.source_count ?? 0,
    fulltext_count: run.fulltext_count ?? 0,
    claim_count: run.claim_count ?? 0,
    coverage: run.coverage ?? 0,
    counter_evidence_coverage: run.counter_evidence_coverage ?? 0,
    model_usage: run.model_usage ?? {},
    stop_reason: run.stop_reason ?? '',
    degraded_sources: run.degraded_sources ?? [],
  }
  const maxRounds = Number(state?.limits.max_rounds ?? run.config.max_rounds ?? 10)
  const budgetProgress = Math.min(100, Math.round(100 * metrics.current_iteration / maxRounds))

  return (
    <div className="research-progress-sheet">
      <div className="research-metric-grid">
        <Statistic title="研究轮次" value={metrics.current_iteration} suffix={`/ ${maxRounds}`} />
        <Statistic title="候选来源" value={metrics.source_count} />
        <Statistic title="已解析全文" value={metrics.fulltext_count} />
        <Statistic title="可核验观点" value={metrics.claim_count} />
      </div>
      <div className="research-coverage-grid">
        <div>
          <span>问题覆盖</span>
          <Progress percent={metrics.coverage} strokeColor="#1f6255" />
        </div>
        <div>
          <span>反证覆盖</span>
          <Progress percent={metrics.counter_evidence_coverage} strokeColor="#b94d32" />
        </div>
        <div>
          <span>检索预算</span>
          <Progress percent={budgetProgress} strokeColor="#8a6a2f" />
        </div>
      </div>
      <div className="research-run-footnote">
        <span>停止条件：{metrics.stop_reason || '仍在取证'}</span>
        <span>Token：{metrics.model_usage.total_tokens?.toLocaleString() ?? '—'}</span>
      </div>
    </div>
  )
}

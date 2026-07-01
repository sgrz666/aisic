import { ArrowRightOutlined, CheckCircleFilled } from '@ant-design/icons'
import { Button, Progress, Tag } from 'antd'

import type { ResearchRoute, ResearchScores } from '../types'

const routeCopy: Record<ResearchRoute, { title: string; description: string; tone: string }> = {
  A: { title: '已有数据分析', description: '整合公开数据与文献证据，进入受控统计分析。', tone: 'green' },
  B: { title: '新数据采集', description: '生成问卷或小实验，等待真实数据回传后分析。', tone: 'gold' },
  C: { title: '理论证据综合', description: '进行概念辨析、理论综述与研究问题重构。', tone: 'blue' },
  D: { title: '探索性研究', description: '仅保留探索假设与验证方向，不生成确定性结论。', tone: 'volcano' },
}

interface GatePanelProps {
  scores: ResearchScores
  suggestedRoute: ResearchRoute
  onConfirm: (route: ResearchRoute) => void
  loading?: boolean
}

export function GatePanel({ scores, suggestedRoute, onConfirm, loading }: GatePanelProps) {
  const route = routeCopy[suggestedRoute]
  return (
    <section className="gate-panel">
      <div className="section-kicker">HUMAN GATE · 必须由研究者确认</div>
      <div className="gate-panel__header">
        <div>
          <h2>研究路径门控</h2>
          <p>系统根据证据充足度与问题可研究性提出建议，不替你做最终决定。</p>
        </div>
        <Tag color={route.tone} icon={<CheckCircleFilled />}>推荐路径</Tag>
      </div>
      <div className="score-grid">
        <div className="score-card">
          <Progress type="dashboard" percent={scores.information_sufficiency} strokeColor="#1f4e5f" size={112} />
          <strong>信息充足度</strong>
          <span>来源数量、可靠性与覆盖度</span>
        </div>
        <div className="score-card">
          <Progress type="dashboard" percent={scores.researchability} strokeColor="#c55232" size={112} />
          <strong>可研究性</strong>
          <span>可测量性、可行性与伦理风险</span>
        </div>
        <div className="route-card">
          <span className="route-card__letter">{suggestedRoute}</span>
          <div>
            <span className="section-kicker">路径 {suggestedRoute}</span>
            <h3>{route.title}</h3>
            <p>{route.description}</p>
          </div>
        </div>
      </div>
      <Button
        aria-label={`确认路径 ${suggestedRoute}`}
        type="primary"
        size="large"
        loading={loading}
        icon={<ArrowRightOutlined />}
        onClick={() => onConfirm(suggestedRoute)}
      >
        确认路径 {suggestedRoute}
      </Button>
    </section>
  )
}

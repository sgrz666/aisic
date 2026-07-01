import {
  BulbOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'

const stages = [
  { keys: ['S0_IDEA'], label: '研究想法', hint: '界定问题', icon: BulbOutlined },
  { keys: ['S1_EVIDENCE'], label: '证据构建', hint: '摄入与核验', icon: FileSearchOutlined },
  { keys: ['S2_GATE'], label: '路径门控', hint: '评分与确认', icon: SafetyCertificateOutlined },
  { keys: ['S3_DESIGN', 'WAITING_FOR_DATA'], label: '研究设计', hint: '问卷与方案', icon: ExperimentOutlined },
  { keys: ['S4_ANALYSIS'], label: '数据分析', hint: '受控统计', icon: DatabaseOutlined },
  { keys: ['S5_REPORT', 'S6_REVIEW', 'COMPLETED', 'BLOCKED'], label: '报告复审', hint: '引用与边界', icon: FileTextOutlined },
]

export function StageRail({ currentStage }: { currentStage: string }) {
  const currentIndex = Math.max(
    0,
    stages.findIndex((stage) => stage.keys.includes(currentStage)),
  )

  return (
    <nav className="stage-rail" aria-label="研究阶段">
      <div className="stage-rail__eyebrow">RESEARCH FLOW</div>
      <ol>
        {stages.map((stage, index) => {
          const Icon = stage.icon
          const state = index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'future'
          return (
            <li key={stage.label} className={`stage-item stage-item--${state}`}>
              <span className="stage-item__index">{String(index + 1).padStart(2, '0')}</span>
              <span className="stage-item__icon"><Icon /></span>
              <span className="stage-item__copy">
                <span aria-current={state === 'current' ? 'step' : undefined}>{stage.label}</span>
                <small>{stage.hint}</small>
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}


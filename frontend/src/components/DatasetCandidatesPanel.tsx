import { CheckCircleFilled, CloseCircleOutlined, LinkOutlined } from '@ant-design/icons'
import { Progress, Tag } from 'antd'

import type { DatasetCandidate } from '../types'

const sourceNames: Record<string, string> = {
  world_bank: 'World Bank',
  unicef: 'UNICEF',
  unesco_uis: 'UNESCO UIS',
  china_moe: '中国教育部',
}

interface DatasetCandidatesPanelProps {
  candidates: DatasetCandidate[]
}

export function DatasetCandidatesPanel({
  candidates,
}: DatasetCandidatesPanelProps) {
  if (candidates.length === 0) return null

  return (
    <section className="dataset-candidates" aria-labelledby="dataset-candidates-title">
      <div className="dataset-candidates__heading">
        <div>
          <span className="section-kicker">PUBLIC DATA PROVENANCE</span>
          <h3 id="dataset-candidates-title">开放数据候选</h3>
        </div>
        <span>{candidates.length} 个已审查来源</span>
      </div>
      <div className="dataset-candidates__list">
        {candidates.map((candidate) => {
          const details = candidate.candidate_json
          const excluded = details.excluded_reason
          return (
            <article
              className={`dataset-candidate${candidate.selected ? ' dataset-candidate--selected' : ''}`}
              key={candidate.id}
            >
              <div className="dataset-candidate__source">
                <strong>{sourceNames[candidate.source] ?? candidate.source}</strong>
                {candidate.selected ? (
                  <Tag color="green" icon={<CheckCircleFilled />}>已选用</Tag>
                ) : excluded ? (
                  <Tag color="error" icon={<CloseCircleOutlined />}>已排除</Tag>
                ) : (
                  <Tag>候选</Tag>
                )}
              </div>
              <h4>{candidate.title}</h4>
              <div className="dataset-candidate__metrics">
                <span>变量覆盖 {details.variable_coverage ?? 0}%</span>
                <span>许可 {details.license_name || '待核验'}</span>
                <span>综合评分 {candidate.score}</span>
              </div>
              <Progress
                percent={candidate.score}
                showInfo={false}
                strokeColor={candidate.selected ? '#4b8e67' : '#1f4e5f'}
                size="small"
              />
              {excluded && <p className="dataset-candidate__reason">排除原因：{excluded}</p>}
              {details.variable_mapping && (
                <p className="dataset-candidate__mapping">
                  {Object.entries(details.variable_mapping)
                    .map(([concept, field]) => `${concept} → ${field}`)
                    .join(' · ')}
                </p>
              )}
              <a
                aria-label="查看来源"
                href={candidate.provenance_url}
                target="_blank"
                rel="noreferrer"
              >
                <LinkOutlined /> 查看来源
              </a>
            </article>
          )
        })}
      </div>
    </section>
  )
}

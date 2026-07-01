import { CheckCircleFilled, ExclamationCircleFilled, LinkOutlined } from '@ant-design/icons'
import { Drawer, Empty, Tag } from 'antd'

import type { EvidenceCard } from '../types'

export function EvidenceDrawer({
  open,
  onClose,
  evidence,
}: {
  open: boolean
  onClose: () => void
  evidence: EvidenceCard[]
}) {
  return (
    <Drawer title="证据与风险" width={440} open={open} onClose={onClose}>
      <div className="evidence-summary">
        <strong>{evidence.length}</strong>
        <span>条证据已进入当前项目记忆</span>
      </div>
      {evidence.length ? (
        <div className="evidence-list">
          {evidence.map((card, index) => (
            <article className="evidence-card" key={card.id}>
              <div className="evidence-card__meta">
                <span>E-{String(index + 1).padStart(2, '0')}</span>
                <Tag
                  color={card.trust_status === 'PASS' ? 'success' : 'warning'}
                  icon={card.trust_status === 'PASS' ? <CheckCircleFilled /> : <ExclamationCircleFilled />}
                >
                  {card.trust_status}
                </Tag>
              </div>
              <h4>{card.title}</h4>
              <p>{card.excerpt}</p>
              <small>{card.locator}</small>
              {card.source_url.startsWith('http') && (
                <a href={card.source_url} target="_blank" rel="noreferrer"><LinkOutlined /> 查看来源</a>
              )}
            </article>
          ))}
        </div>
      ) : (
        <Empty description="尚未构建证据" />
      )}
    </Drawer>
  )
}


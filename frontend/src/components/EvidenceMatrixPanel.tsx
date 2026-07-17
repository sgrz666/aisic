import { Collapse, Empty, Tag } from 'antd'

import type { EvidenceGraph } from '../types'

interface EvidenceMatrixPanelProps {
  graph: EvidenceGraph | null
}

const stanceCopy = {
  supports: { label: '支持', color: 'green' },
  counter: { label: '反证', color: 'red' },
  qualifies: { label: '限定', color: 'gold' },
} as const

export function EvidenceMatrixPanel({ graph }: EvidenceMatrixPanelProps) {
  if (!graph?.claims.length) {
    return <Empty description="尚未形成带原文定位的证据关系" />
  }

  return (
    <Collapse
      ghost
      className="evidence-matrix"
      items={graph.claims.map((claim) => {
        const evidence = graph.evidence.filter((item) => item.claim_id === claim.id)
        return {
          key: claim.id,
          label: <span className="evidence-claim">{claim.statement}</span>,
          extra: <span className="evidence-count">{evidence.length} 条证据</span>,
          children: (
            <div className="evidence-stack">
              {evidence.map((item) => {
                const stance = stanceCopy[item.stance]
                return (
                  <article className="evidence-slip" key={item.id}>
                    <header>
                      <Tag color={stance.color}>{stance.label}</Tag>
                      <strong>{item.document.title}</strong>
                      <span>{item.locator}</span>
                    </header>
                    <p>{item.excerpt}</p>
                    <footer>
                      <span>可信度 {item.confidence}</span>
                      <a href={item.document.url} target="_blank" rel="noreferrer">查看原始来源</a>
                    </footer>
                  </article>
                )
              })}
            </div>
          ),
        }
      })}
    />
  )
}

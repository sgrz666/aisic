import { Alert, Table, Tag } from 'antd'
import type { Questionnaire, QuestionnaireItem } from '../types'

export function QuestionnairePanel({ questionnaire }: { questionnaire?: Questionnaire }) {
  const items = questionnaire?.items ?? []
  return (
    <section className="paper-panel">
      <div className="section-kicker">INSTRUMENT · 可编辑后导出</div>
      <h2>{questionnaire?.title ?? '研究工具'}</h2>
      <Alert
        type="warning"
        showIcon
        message="请在真实发放前完成伦理审查、知情同意与量表授权确认。"
      />
      <Table<QuestionnaireItem>
        rowKey="id"
        pagination={false}
        dataSource={items}
        columns={[
          { title: '编号', dataIndex: 'id', width: 72 },
          { title: '维度', dataIndex: 'dimension', width: 130, render: (value: string) => <Tag>{value}</Tag> },
          { title: '题项', dataIndex: 'text' },
          { title: '题型', dataIndex: 'type', width: 130 },
        ]}
      />
    </section>
  )
}

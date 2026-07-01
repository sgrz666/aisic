import { DownloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { Button, Descriptions, Tag } from 'antd'

import { reportDownloadUrl } from '../api'
import type { ResearchReport, ReviewResult } from '../types'

interface ReportPanelProps {
  projectId: string
  report: ResearchReport
  review: ReviewResult
}

export function ReportPanel({ projectId, report, review }: ReportPanelProps) {
  const blocked = review?.overall === 'BLOCK'
  return (
    <section className="paper-panel report-panel">
      <div className="report-panel__top">
        <div><div className="section-kicker">RESEARCH ARTIFACT</div><h2>{report.title ?? '教育学科学假设与研究计划'}</h2></div>
        <Tag color={blocked ? 'error' : review?.overall === 'PASS' ? 'success' : 'warning'} icon={<SafetyCertificateOutlined />}>
          {review?.overall ?? '待复审'}
        </Tag>
      </div>
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="待研究问题">{report.problem}</Descriptions.Item>
        <Descriptions.Item label="解决思路">{report.rationale}</Descriptions.Item>
        <Descriptions.Item label="方法论">{report.methods}</Descriptions.Item>
        <Descriptions.Item label="结果边界">{report.results}</Descriptions.Item>
        <Descriptions.Item label="局限与伦理">{report.limitations_ethics}</Descriptions.Item>
      </Descriptions>
      <div className="report-actions">
        <Button icon={<DownloadOutlined />} href={reportDownloadUrl(projectId, 'draft')}>下载草稿 DOCX</Button>
        <Button type="primary" disabled={blocked || !review?.overall} icon={<DownloadOutlined />} href={reportDownloadUrl(projectId, 'final')}>
          下载复审通过版
        </Button>
      </div>
    </section>
  )
}

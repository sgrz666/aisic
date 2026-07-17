import { DownloadOutlined, FileDoneOutlined } from '@ant-design/icons'
import { Button, Result } from 'antd'

import { reportDownloadUrl } from '../api'
import type { AutonomousStatus } from '../types'

interface ResearchReportEntryProps {
  projectId: string
  status: AutonomousStatus
}

export function ResearchReportEntry({ projectId, status }: ResearchReportEntryProps) {
  const ready = status === 'completed'
  return (
    <Result
      icon={<FileDoneOutlined />}
      status={ready ? 'success' : 'info'}
      title={ready ? '证据化研究报告已完成' : '报告将在取证与盲审完成后开放'}
      subTitle="报告 v3 会保留检索方法、冲突证据、结论置信度和片段级定位。"
      extra={ready ? (
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          href={reportDownloadUrl(projectId, 'final')}
          aria-label="下载证据化报告"
        >
          下载证据化报告
        </Button>
      ) : null}
    />
  )
}

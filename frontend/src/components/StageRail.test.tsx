import { render, screen } from '@testing-library/react'

import { StageRail } from './StageRail'

test('marks gate stage as current and shows the complete research lifecycle', () => {
  render(<StageRail currentStage="S2_GATE" />)

  expect(screen.getByText('路径门控')).toHaveAttribute('aria-current', 'step')
  expect(screen.getByText('研究想法')).toBeInTheDocument()
  expect(screen.getByText('证据构建')).toBeInTheDocument()
  expect(screen.getByText('研究设计')).toBeInTheDocument()
  expect(screen.getByText('数据分析')).toBeInTheDocument()
  expect(screen.getByText('报告复审')).toBeInTheDocument()
})


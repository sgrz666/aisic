import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { DashboardPage } from './DashboardPage'
import * as api from '../api'

vi.mock('../api', () => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
}))

test('creates a project from a research idea', async () => {
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.createProject).mockResolvedValue({
    id: 'p1',
    owner_id: 'local-user',
    title: 'AI 焦虑研究',
    idea_text: '分析大学生 AI 焦虑度与专业的关系',
    stage: 'S0_IDEA',
    route: null,
    suggested_route: null,
    research_problem: {},
    scores: {},
    study_design: {},
    analysis_result: {},
    report: {},
    review: {},
    evidence_count: 0,
  })

  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )

  expect(await screen.findByText('把模糊的研究灵感，变成可验证的教育研究。')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /创建研究项目/ }))
  await userEvent.type(screen.getByLabelText('项目名称'), 'AI 焦虑研究')
  await userEvent.type(screen.getByLabelText('研究想法'), '分析大学生 AI 焦虑度与专业的关系')
  await userEvent.click(screen.getByRole('button', { name: '创建并进入研究' }))

  await waitFor(() =>
    expect(api.createProject).toHaveBeenCalledWith({
      title: 'AI 焦虑研究',
      idea_text: '分析大学生 AI 焦虑度与专业的关系',
    }),
  )
})


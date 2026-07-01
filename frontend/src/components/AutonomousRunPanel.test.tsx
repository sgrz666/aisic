import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import type { AutonomousRun, DatasetCandidate } from '../types'
import { AutonomousRunPanel } from './AutonomousRunPanel'
import { DatasetCandidatesPanel } from './DatasetCandidatesPanel'

vi.mock('../api', () => ({
  startAutonomousResearch: vi.fn(),
  getAutonomousRun: vi.fn(),
  cancelAutonomousRun: vi.fn(),
  resumeAutonomousRun: vi.fn(),
  listDatasetCandidates: vi.fn(),
}))

const gateRun: AutonomousRun = {
  id: 'run-1',
  project_id: 'p1',
  task_id: 'task-1',
  status: 'awaiting_route_confirmation',
  current_node: 'human_gate',
  config: {},
  pause_reason: { suggested_route: 'A' },
  cancel_requested: false,
  error: {},
}

describe('AutonomousRunPanel', () => {
  beforeEach(() => {
    vi.mocked(api.startAutonomousResearch).mockResolvedValue({
      run_id: 'run-1',
      task_id: 'task-1',
      status: 'awaiting_route_confirmation',
    })
    vi.mocked(api.getAutonomousRun).mockResolvedValue(gateRun)
    vi.mocked(api.listDatasetCandidates).mockResolvedValue([])
  })

  it('starts autonomous research and shows the human gate pause', async () => {
    const onChanged = vi.fn()
    render(
      <AutonomousRunPanel projectId="p1" run={null} onChanged={onChanged} />,
    )

    await userEvent.click(screen.getByRole('button', { name: '启动自动研究' }))

    expect(await screen.findByText('等待你确认研究路径')).toBeVisible()
    expect(api.startAutonomousResearch).toHaveBeenCalledWith('p1')
    expect(onChanged).toHaveBeenCalledWith(gateRun)
  })

  it('shows candidate provenance and exclusion reason', () => {
    const candidate: DatasetCandidate = {
      id: 'candidate-1',
      run_id: 'run-1',
      project_id: 'p1',
      source: 'world_bank',
      external_id: 'SP.POP.TOTL',
      title: 'Population, total',
      provenance_url: 'https://api.worldbank.org/v2/indicator/SP.POP.TOTL',
      score: 92,
      selected: true,
      candidate_json: {
        variable_coverage: 100,
        license_name: 'CC BY 4.0',
        variable_mapping: { 'school-age population': 'value' },
        excluded_reason: '',
      },
    }

    render(<DatasetCandidatesPanel candidates={[candidate]} />)

    expect(screen.getByText('World Bank')).toBeVisible()
    expect(screen.getByText(/变量覆盖 100%/)).toBeVisible()
    expect(screen.getByRole('link', { name: '查看来源' })).toHaveAttribute(
      'href',
      candidate.provenance_url,
    )
  })
})

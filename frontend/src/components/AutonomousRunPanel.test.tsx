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
  getAutonomousResearchState: vi.fn(),
  getAutonomousEvidenceGraph: vi.fn(),
  reportDownloadUrl: vi.fn(() => '/report.docx'),
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
  current_iteration: 2,
  source_count: 12,
  fulltext_count: 6,
  claim_count: 4,
  coverage: 80,
  counter_evidence_coverage: 50,
  model_usage: { total_tokens: 1200 },
  stop_reason: 'evidence_saturated',
  degraded_sources: [],
  quality_metrics: {
    subquestion_coverage: 80,
    independent_source_coverage: 50,
    counter_search_coverage: 100,
    grounding_pass_rate: 100,
  },
  quality_gate_status: 'LIMITED',
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
    vi.mocked(api.getAutonomousResearchState).mockResolvedValue({
      run_id: 'run-1',
      limits: { max_fulltexts: 60 },
      metrics: {
        current_iteration: 2,
        source_count: 12,
        fulltext_count: 6,
        claim_count: 4,
        coverage: 80,
        counter_evidence_coverage: 50,
        model_usage: { total_tokens: 1200 },
        stop_reason: 'evidence_saturated',
        degraded_sources: [],
        quality_gate_status: 'LIMITED',
        subquestion_coverage: 80,
        independent_source_coverage: 50,
        counter_search_coverage: 100,
        grounding_pass_rate: 100,
      },
      iterations: [],
    })
    vi.mocked(api.getAutonomousEvidenceGraph).mockResolvedValue({
      subquestions: [{ id: 'sq-1', ordinal: 0, question: '干预是否降低焦虑？', required: true, status: 'covered' }],
      claims: [{ id: 'claim-1', statement: '干预与较低焦虑相关。', claim_type: 'finding', subquestion_ids: ['sq-1'] }],
      evidence: [{
        id: 'e-1',
        claim_id: 'claim-1',
        stance: 'supports',
        confidence: 88,
        locator: '第 4 页',
        excerpt: '干预组焦虑得分较低。',
        validation_status: 'validated',
        entailment_score: 91,
        validator_model: 'qwen3.7-plus',
        independent_group: 'doi:10.1/example',
        document: { id: 'd-1', title: '开放研究', url: 'https://example.edu/paper', license_name: 'CC BY 4.0' },
      }],
    })
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

  it('keeps successful dataset candidates when optional research views fail', async () => {
    vi.mocked(api.listDatasetCandidates).mockResolvedValue([{
      id: 'candidate-1',
      run_id: 'run-1',
      project_id: 'p1',
      source: 'world_bank',
      external_id: 'SP.POP.TOTL',
      title: 'Population, total',
      provenance_url: 'https://api.worldbank.org',
      score: 90,
      selected: true,
      candidate_json: {},
    }])
    vi.mocked(api.getAutonomousResearchState).mockRejectedValue(new Error('not available'))
    vi.mocked(api.getAutonomousEvidenceGraph).mockRejectedValue(new Error('not available'))

    render(<AutonomousRunPanel projectId="p1" run={gateRun} onChanged={vi.fn()} />)

    expect(await screen.findByText('World Bank')).toBeVisible()
  })

  it('shows real research metrics, evidence matrix and final report entry', async () => {
    render(
      <AutonomousRunPanel
        projectId="p1"
        run={{ ...gateRun, status: 'completed', current_node: 'completed' }}
        onChanged={vi.fn()}
      />,
    )

    expect(await screen.findByText('已解析全文')).toBeVisible()
    expect(screen.getByText('6')).toBeVisible()
    expect(screen.getByText('质量门禁')).toBeVisible()
    expect(screen.getByText('独立来源覆盖')).toBeVisible()
    expect(screen.getByText('原文核验')).toBeVisible()

    await userEvent.click(screen.getByRole('tab', { name: '证据矩阵' }))
    expect(await screen.findByText('干预与较低焦虑相关。')).toBeVisible()
    await userEvent.click(screen.getByText('干预与较低焦虑相关。'))
    expect(await screen.findByText(/第 4 页/)).toBeVisible()
    expect(screen.getByText('已核验')).toBeVisible()

    await userEvent.click(screen.getByRole('tab', { name: '最终报告' }))
    expect(screen.getByRole('link', { name: '下载证据化报告' })).toHaveAttribute(
      'href',
      '/report.docx',
    )
  })
})

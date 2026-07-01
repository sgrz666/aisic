import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import * as api from '../api'
import type { ResearchReport, ReviewResult } from '../types'
import { ReportPanel } from './ReportPanel'

vi.mock('../api', () => ({
  reportDownloadUrl: vi.fn(() => '/report.docx'),
  regenerateReport: vi.fn().mockResolvedValue({ task_id: 't1', status: 'completed' }),
}))

it('renders V2 report status, datasets, metrics and regeneration action', async () => {
  const report: ResearchReport = {
    schema_version: 2,
    paper_title: '生成式人工智能使用与大学生AI焦虑的可行性研究',
    abstract: '摘要正文',
    keywords: ['AI焦虑', '大学生', '可行性'],
    problem_statement: { current_limitation: '缺少真实心理健康指标', knowledge_gap: '构念未对齐', research_question: '变量如何关联？', evidence_ids: [] },
    rationale: { innovation: '区分模拟与实证', reasoning_chain: ['一', '二', '三', '四'], evidence_ids: [] },
    technical_details: [{ purpose: '信度', method: "Cronbach's alpha", stack: ['pandas'], execution_status: 'executed', rationale: '量表检验' }],
    datasets: {
      source: [],
      simulation_input: [{ name: '模拟问卷', origin_type: 'synthetic_demo', role: '流程验证', rows: 120 }],
      target: { population: '在校大学生', features: ['AI焦虑', '心理健康'], label: '心理健康得分', minimum_sample_size: 300 },
    },
    methods: [{ step: 1, name: '量表构造', input: '题项', procedure: '计算均值', output: '量表得分' }],
    experiments: { baselines: [{ name: '零模型', description: '仅截距', purpose: '比较' }], metrics: [{ name: 'Pearson r', definition: '相关', success_criterion: '报告CI' }], validation_design: '独立样本', robustness_checks: [] },
    results: { kind: 'simulation_feasibility', status: '现实效应待验证', sample_size: 120, statistical_findings: [], feasibility_conclusion: '流程可行', limitations: ['模拟数据'] },
    limitations_ethics: { causal_boundary: '不能推断因果', sample_limitations: ['模拟'], privacy: ['匿名'], consent: ['知情同意'] },
    references: [],
  }
  const review: ReviewResult = { overall: 'WARN', checks: { construct_alignment: { status: 'WARN', message: '构念未对齐' } } }
  const onRegenerated = vi.fn()

  render(<ReportPanel projectId="p1" report={report} review={review} onRegenerated={onRegenerated} />)

  expect(screen.getAllByText('模拟可行性')[0]).toBeVisible()
  expect(screen.getByText("Cronbach's alpha")).toBeVisible()
  expect(screen.getByText('Target · 拟采集验证数据')).toBeVisible()
  expect(screen.getByText(/模拟问卷/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: '重新生成 V2' }))
  expect(api.regenerateReport).toHaveBeenCalledWith('p1')
  expect(onRegenerated).toHaveBeenCalled()
})

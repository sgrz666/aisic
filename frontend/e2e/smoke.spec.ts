import { expect, test } from '@playwright/test'

test('首页可用并能创建项目进入 S1', async ({ page }) => {
  const consoleErrors: string[] = []
  let ideaParsed = false
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.route(/\/api\/v1\/projects\/[^/]+$/, async (route) => {
    if (route.request().method() !== 'GET' || !ideaParsed) {
      await route.continue()
      return
    }
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), stage: 'S1_EVIDENCE' } })
  })
  await page.route(/\/api\/v1\/projects\/[^/]+\/idea-runs$/, async (route) => {
    ideaParsed = true
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: 'idea-browser-1', status: 'completed' }),
    })
  })

  await page.goto('/')
  await expect(page).toHaveTitle(/教育智研/)
  await expect(page.getByRole('heading', { name: /把模糊的研究灵感/ })).toBeVisible()
  await expect(page.locator('.vite-error-overlay')).toHaveCount(0)

  await page.getByRole('button', { name: '创建研究项目' }).click()
  const uniqueTitle = `浏览器验收-${Date.now()}`
  await page.getByLabel('项目名称').fill(uniqueTitle)
  await page.getByLabel('研究想法').fill('分析大学生 AI 焦虑度与专业的关系')
  await page.getByRole('button', { name: '创建并进入研究' }).click()

  await expect(page).toHaveURL(/\/projects\//)
  await expect(page.getByText(uniqueTitle)).toBeVisible()
  await page.getByRole('button', { name: '解析研究问题' }).click()
  await expect(page.getByRole('heading', { name: '建立可追溯证据包' })).toBeVisible()

  await page.screenshot({ path: 'test-results/workspace-smoke.png', fullPage: true })
  expect(consoleErrors).toEqual([])
})

test('自动研究展示进度、数据来源并通过路径门禁', async ({ page }) => {
  let autonomousStarted = false
  let routeConfirmed = false
  const run = {
    id: 'run-browser-1',
    project_id: '',
    task_id: 'task-browser-1',
    status: 'awaiting_route_confirmation',
    current_node: 'human_gate',
    config: {},
    pause_reason: { suggested_route: 'A' },
    cancel_requested: false,
    error: {},
  }

  await page.route(/\/api\/v1\/projects\/[^/]+$/, async (route) => {
    if (route.request().method() !== 'GET' || !autonomousStarted) {
      await route.continue()
      return
    }
    const response = await route.fetch()
    const project = await response.json()
    await route.fulfill({
      response,
      json: {
        ...project,
        stage: routeConfirmed ? 'COMPLETED' : 'S2_GATE',
        route: routeConfirmed ? 'A' : null,
        suggested_route: 'A',
        scores: { information_sufficiency: 90, researchability: 88 },
        report: routeConfirmed ? { title: '自动研究报告', result_kind: 'observed' } : {},
        review: routeConfirmed ? { overall: 'PASS', checks: {} } : {},
      },
    })
  })
  await page.route(/\/api\/v1\/projects\/[^/]+\/autonomous-runs$/, async (route) => {
    autonomousStarted = true
    const projectId = route.request().url().split('/').at(-2) ?? ''
    run.project_id = projectId
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ run_id: run.id, task_id: run.task_id, status: run.status }),
    })
  })
  await page.route(`**/api/v1/autonomous-runs/${run.id}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ...run,
        status: routeConfirmed ? 'completed' : run.status,
        current_node: routeConfirmed ? 'completed' : run.current_node,
      }),
    })
  })
  await page.route(`**/api/v1/autonomous-runs/${run.id}/dataset-candidates`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([{
        id: 'candidate-browser-1',
        run_id: run.id,
        project_id: run.project_id,
        source: 'world_bank',
        external_id: 'SP.POP.TOTL',
        title: 'Population, total',
        provenance_url: 'https://api.worldbank.org/v2/indicator/SP.POP.TOTL',
        score: 92,
        selected: true,
        candidate_json: { variable_coverage: 100, license_name: 'CC BY 4.0' },
      }]),
    })
  })
  await page.route(/\/api\/v1\/projects\/[^/]+\/route-confirmations$/, async (route) => {
    routeConfirmed = true
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  await page.route(`**/api/v1/autonomous-runs/${run.id}/resume`, async (route) => {
    routeConfirmed = true
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ run_id: run.id, task_id: run.task_id, status: 'completed' }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '创建研究项目' }).click()
  await page.getByLabel('项目名称').fill(`自动研究验收 ${Date.now()}`)
  await page.getByLabel('研究想法').fill('人口变化对基础教育资源配置的影响')
  await page.getByRole('button', { name: '创建并进入研究' }).click()

  await page.getByRole('button', { name: '启动自动研究' }).click()
  await expect(page.getByText('等待你确认研究路径')).toBeVisible()
  await expect(page.getByText('World Bank')).toBeVisible()
  await page.getByRole('button', { name: '确认路径 A' }).click()
  await expect(page.getByText('自治研究流程已完成')).toBeVisible()
})

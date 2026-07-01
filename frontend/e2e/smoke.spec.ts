import { expect, test } from '@playwright/test'

test('首页可用并能创建项目进入 S1', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
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

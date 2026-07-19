import { defineConfig } from '@playwright/test'

const executablePath = process.env.PLAYWRIGHT_CHROME_PATH
  ?? (process.platform === 'win32'
    ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    : undefined)
const webPort = process.env.WEB_PORT ?? '5174'
const webURL = `http://127.0.0.1:${webPort}`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: {
    baseURL: webURL,
    viewport: { width: 1440, height: 960 },
    launchOptions: executablePath ? { executablePath } : {},
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: '..\\backend\\.venv\\Scripts\\python.exe -m uvicorn edusci.app:app --app-dir ../backend --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      url: webURL,
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})

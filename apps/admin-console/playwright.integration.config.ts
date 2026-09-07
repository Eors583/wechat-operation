import { defineConfig, devices } from '@playwright/test'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

const appRoot = import.meta.dirname
const backendRoot = resolve(appRoot, '../../services/platform-backend')
const databasePath = join(tmpdir(), `wechat-ai-admin-e2e-${process.pid}.db`).replaceAll('\\', '/')

const backendEnvironment = {
  ...process.env,
  APP_ENV: 'test',
  DATABASE_URL: `sqlite+aiosqlite:///${databasePath}`,
  RETRIEVAL_DATABASE_URL: '',
  TOKEN_SECRET: 'integration-test-token-secret-32-characters-minimum',
  COOKIE_SECURE: 'false',
  AUTO_CREATE_SCHEMA: 'false',
  ALLOWED_ORIGINS: 'http://127.0.0.1:4175',
  E2E_MODEL_KEY: 'e2e-model-secret',
}

export default defineConfig({
  testDir: './tests/integration',
  outputDir: './test-results/playwright-integration',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report-integration', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4175',
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command:
        'uv run alembic upgrade head && uv run python -m app.cli create-admin --username e2e-admin --password AdminE2E2026_ && uv run uvicorn app.main:app --host 127.0.0.1 --port 9011',
      cwd: backendRoot,
      env: backendEnvironment,
      url: 'http://127.0.0.1:9011/health/ready',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'pnpm exec vite --host 127.0.0.1 --port 4175',
      cwd: appRoot,
      env: {
        ...process.env,
        VITE_ADMIN_API_BASE: 'http://127.0.0.1:9011',
      },
      url: 'http://127.0.0.1:4175/login',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'real-backend-390',
      use: { viewport: { width: 390, height: 844 } },
    },
    {
      name: 'real-backend-1024',
      use: { viewport: { width: 1024, height: 768 } },
    },
    {
      name: 'real-backend-1280',
      use: { viewport: { width: 1280, height: 720 } },
    },
    {
      name: 'real-backend-1440',
      use: { viewport: { width: 1440, height: 900 } },
    },
  ],
})

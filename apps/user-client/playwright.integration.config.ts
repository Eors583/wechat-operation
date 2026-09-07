import { defineConfig, devices } from '@playwright/test'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

const appRoot = import.meta.dirname
const backendRoot = resolve(appRoot, '../../services/platform-backend')
const databasePath = join(tmpdir(), `wechat-ai-user-e2e-${process.pid}.db`).replaceAll('\\', '/')

const backendEnvironment = {
  ...process.env,
  APP_ENV: 'test',
  DATABASE_URL: `sqlite+aiosqlite:///${databasePath}`,
  RETRIEVAL_DATABASE_URL: '',
  TOKEN_SECRET: 'integration-test-token-secret-32-characters-minimum',
  COOKIE_SECURE: 'false',
  AUTO_CREATE_SCHEMA: 'false',
  LAYOUT_PROVIDER_MODE: 'wechat_public',
  WECHAT_PROVIDER_MODE: 'direct',
  ALLOWED_ORIGINS: 'http://127.0.0.1:4174',
}

export default defineConfig({
  testDir: './tests/integration',
  outputDir: './test-results/playwright-integration',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report-integration', open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command:
        'uv run alembic upgrade head && uv run uvicorn app.main:app --host 127.0.0.1 --port 9010',
      cwd: backendRoot,
      env: backendEnvironment,
      url: 'http://127.0.0.1:9010/health/ready',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'node ./node_modules/@quasar/app-vite/bin/quasar.js dev -p 4174',
      cwd: appRoot,
      env: {
        ...process.env,
        VITE_API_MODE: 'remote',
        VITE_API_BASE_URL: 'http://127.0.0.1:9010/api/v1',
      },
      url: 'http://127.0.0.1:4174/register',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'real-backend-chromium',
      use: { ...devices['Desktop Chrome'], channel: process.env.CI ? undefined : 'chrome' },
    },
  ],
})

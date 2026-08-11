import { defineConfig, devices, type PlaywrightTestConfig } from '@playwright/test'

const env =
  (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}

const host = env.PLAYWRIGHT_HOST ?? 'localhost'
const port = env.PLAYWRIGHT_PORT ?? '8080'
const defaultBaseURL = `http://${host}:${port}`
const baseURL = env.PLAYWRIGHT_BASE_URL ?? defaultBaseURL
const shouldStartServer = !['0', 'false'].includes(
  (env.PLAYWRIGHT_START_SERVER ?? '').toLowerCase()
)

const webServer = shouldStartServer
  ? {
      command: `pnpm dev -- --host ${host} --port ${port}`,
      url: baseURL,
      reuseExistingServer: !env.CI,
      stdout: 'pipe' as const,
      stderr: 'pipe' as const,
    }
  : undefined

const AUTH_FILE = 'playwright/.auth/admin.json'
const chromiumExecutablePath = env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
const NON_ADMIN_TESTS = /.*[\\/](?:common|user)[\\/].*\.spec\.ts/
const ADMIN_TESTS = /.*[\\/]admin[\\/].*\.spec\.ts/
const chromiumUse = {
  ...devices['Desktop Chrome'],
  ...(chromiumExecutablePath ? { launchOptions: { executablePath: chromiumExecutablePath } } : {}),
}

const config: PlaywrightTestConfig = {
  testDir: './tests/e2e',
  fullyParallel: true,
  retries: env.CI ? 2 : 0,
  reporter: [
    [env.CI ? 'dot' : 'list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  outputDir: './playwright-results/',
  use: {
    baseURL,
    trace: env.CI ? 'retain-on-failure' : 'on',
    screenshot: env.CI ? 'only-on-failure' : 'on',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: 'chromium',
      testMatch: NON_ADMIN_TESTS,
      use: chromiumUse,
    },
    {
      name: 'chromium-admin',
      dependencies: ['setup'],
      testMatch: ADMIN_TESTS,
      use: chromiumUse,
    },
    {
      name: 'firefox',
      testMatch: NON_ADMIN_TESTS,
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'firefox-admin',
      dependencies: ['setup'],
      testMatch: ADMIN_TESTS,
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      testMatch: NON_ADMIN_TESTS,
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'webkit-admin',
      dependencies: ['setup'],
      testMatch: ADMIN_TESTS,
      use: { ...devices['Desktop Safari'] },
    },
  ],
  ...(webServer ? { webServer } : {}),
  metadata: {
    authFile: AUTH_FILE,
  },
}

export default defineConfig(config)

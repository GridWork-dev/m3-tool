import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'tests/e2e',
  use: { baseURL: 'http://localhost:4321' },
  webServer: [
    {
      command: 'pnpm preview --port 4321 --ignore-lock',
      url: 'http://localhost:4321',
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'pnpm preview --port 4322 --ignore-lock',
      url: 'http://localhost:4322',
      env: { SITE_OUT_DIR: 'dist-fixture' },
      reuseExistingServer: !process.env.CI,
    },
  ],
  projects: [
    ...(process.env.SHOOT === '1'
      ? [{ name: 'shots', testDir: 'tests/shots', use: { ...devices['Desktop Chrome'] } }]
      : []),
    {
      name: 'real',
      testMatch: 'shared/**',
      metadata: { dataDir: 'data' },
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'fixture',
      testMatch: ['shared/**', 'fixture-only/**'],
      metadata: { dataDir: 'tests/fixtures/site-data' },
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:4322' },
    },
  ],
})

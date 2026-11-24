import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'tests/e2e',
  use: { baseURL: 'http://localhost:4321' },
  webServer: {
    command: 'pnpm preview --port 4321 --ignore-lock',
    url: 'http://localhost:4321',
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: 'real',
      testMatch: 'shared/**',
      metadata: { dataDir: 'data' },
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})

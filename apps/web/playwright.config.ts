import { defineConfig } from '@playwright/test'

declare const process: { env: Record<string, string | undefined> }

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: (process.env.E2E_BASE_URL ?? 'http://localhost:5173').replace(/\/?$/, '/'),
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'] } : {},
    trace: 'retain-on-failure',
  },
})

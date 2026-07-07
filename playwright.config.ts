import { defineConfig, devices } from '@playwright/test';

const pythonCommand = process.env.PYTHON || (process.platform === 'win32'
  ? '.\\.venv\\Scripts\\python.exe'
  : './.venv/bin/python');

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: {
    timeout: 8_000
  },
  reporter: [
    ['html', { open: 'never' }],
    ['list']
  ],
  globalSetup: './tests/helpers/globalSetup.ts',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 12_000,
    navigationTimeout: 20_000
  },
  webServer: {
    command: `${pythonCommand} manage.py runserver 127.0.0.1:8000`,
    url: 'http://127.0.0.1:8000/login/',
    reuseExistingServer: true,
    timeout: 120_000
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } }
    }
  ]
});

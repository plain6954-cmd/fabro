import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'fs';

const localPython = process.platform === 'win32'
  ? (existsSync('.\\env\\Scripts\\python.exe') ? '.\\env\\Scripts\\python.exe' : '.\\.venv\\Scripts\\python.exe')
  : (existsSync('./env/bin/python') ? './env/bin/python' : './.venv/bin/python');
const pythonCommand = process.env.PYTHON || localPython;
const e2ePort = process.env.E2E_PORT || '8001';
const e2eBaseURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${e2ePort}`;

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
  globalTeardown: './tests/helpers/globalTeardown.ts',
  use: {
    baseURL: e2eBaseURL,
    reducedMotion: 'reduce',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 12_000,
    navigationTimeout: 20_000
  },
  webServer: {
    command: `${pythonCommand} manage.py runserver 127.0.0.1:${e2ePort} --noreload`,
    url: `${e2eBaseURL}/health/`,
    env: {
      E2E_TESTING: 'True'
    },
    reuseExistingServer: process.env.E2E_REUSE_SERVER === 'True',
    ...(process.platform === 'win32' ? {} : {
      gracefulShutdown: {
        signal: 'SIGTERM' as const,
        timeout: 1_000
      }
    }),
    stdout: 'ignore',
    stderr: 'ignore',
    timeout: 120_000
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } }
    }
  ]
});

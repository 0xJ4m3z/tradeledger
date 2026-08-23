import { defineConfig, devices } from '@playwright/test';
import path from 'path';

// Dedicated port + SQLite file for the e2e run, kept separate from both the
// desktop app's tradeledger.db and the web app's normal dev tradeledger_web.db
// (see web/config.py) so test runs never depend on — or pollute — manual
// dev-server state.
const PORT = process.env.TRADELEDGER_E2E_PORT || '8010';
const BASE_URL = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(__dirname, '..');
const E2E_DB = path.join(REPO_ROOT, 'tradeledger_e2e.db');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Deletes any stale e2e DB before launching so every full test run seeds
  // sample data fresh (app.database.init_db + web.bootstrap run on startup —
  // see web/main.py) — same fixture state every time, no drift between runs.
  webServer: {
    command: `bash -c "rm -f '${E2E_DB}' && '${PYTHON}' run_web.py"`,
    cwd: REPO_ROOT,
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      TRADELEDGER_WEB_HOST: '127.0.0.1',
      TRADELEDGER_WEB_PORT: PORT,
      TRADELEDGER_DB: E2E_DB,
    },
  },
});

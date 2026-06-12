import { defineConfig, devices } from '@playwright/test';

// G1-ready: the SUT location is config, never hard-coded in a spec. A future
// multi-SUT profile (see docs/test-strategy.md G1) supplies SUT_BASE_URL and
// the specs do not change. Defaults match functional/conftest.py.
const BASE_URL = process.env.SUT_BASE_URL ?? 'http://localhost:5000';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // CI posture (B20): this layer GATES — a failure reds the run. retries:2 on CI
  // is the idiomatic, honest absorption of transient flake: a test that only
  // passes on retry is reported as "flaky" (visible, not hidden), and is bounded
  // and automatic — not a human "just rerun". Locally we never retry, so flakes
  // surface immediately. Paired with the scrollIntoView shim in fixtures.ts
  // (R-018), the one known flake source is already mitigated.
  retries: process.env.CI ? 2 : 0,
  // Serialise on CI so the state-mutating booking journey never races another
  // worker for a free slot (the suite brings up its own ephemeral SUT).
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'reports/html', open: 'never' }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    // Chromium only for now, matching the Python functional suite. Cross-browser
    // (firefox/webkit) is tracked as backlog B6.
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});

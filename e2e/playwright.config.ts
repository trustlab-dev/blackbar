import { defineConfig, devices } from '@playwright/test';
import { BASE_URL } from './lib/config';

/**
 * BlackBar E2E — drives the real docker-compose stack.
 *
 * `workers: 1` deliberately: all specs share one live backend + database, so
 * serial execution avoids cross-test data races and keeps us under the
 * backend's per-IP login rate limit. Bump only if you point each worker at an
 * isolated stack.
 */
export default defineConfig({
  testDir: './specs',
  globalSetup: require.resolve('./global-setup'),
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

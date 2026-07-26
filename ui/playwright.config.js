const { defineConfig, devices } = require('@playwright/test');
const os = require('node:os');
const path = require('node:path');

const PORT = Number(process.env.EII_UI_TEST_PORT || 4173);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const BROWSER_CHANNEL = process.env.EII_PLAYWRIGHT_CHANNEL || 'chrome';

module.exports = defineConfig({
  testDir: './tests',
  // CI overrides this to a workspace path so failure artifacts (diffs,
  // traces) can be uploaded; locally results stay out of the repo.
  outputDir: process.env.EII_PLAYWRIGHT_OUTPUT || path.join(os.tmpdir(), 'ultraisolator-playwright-results'),
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  webServer: {
    // Renderer QA serves the already-built static bundle. The normal dev
    // command remains fail-closed behind the Administrator elevation probe.
    command: `npm run preview:test -- --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
    stdout: 'pipe',
    stderr: 'pipe'
  },
  use: {
    baseURL: BASE_URL,
    colorScheme: 'dark',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: { width: 1366, height: 768 }
  },
  projects: [
    {
      name: `${BROWSER_CHANNEL}-1366`,
      use: {
        ...devices['Desktop Chrome'],
        channel: BROWSER_CHANNEL,
        viewport: { width: 1366, height: 768 },
        deviceScaleFactor: 1
      }
    }
  ],
  expect: {
    timeout: 10000,
    toHaveScreenshot: {
      // Locally the baselines are a byte-identical oracle (this is what
      // verified the CSS flatten). CI uses the runner's system Chrome
      // (channel: 'chrome'), whose version and font rasterization vary
      // between runner images, so cross-machine antialiasing noise needs the
      // historical 0.5% allowance there.
      maxDiffPixelRatio: process.env.CI ? 0.005 : 0
    }
  }
});

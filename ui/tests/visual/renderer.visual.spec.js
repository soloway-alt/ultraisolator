const { expect, test } = require('@playwright/test');
const { gotoMockedRenderer, installRendererMock, waitForAppReady } = require('../fixtures/rendererMock');

test.beforeEach(() => {
  expect(typeof installRendererMock).toBe('function');
});

test.describe('renderer visual regression', () => {
  test('Dashboard command center', async ({ page }) => {
    await gotoMockedRenderer(page, '#dashboard');
    await waitForAppReady(page, '.dashboard-profile-hero');
    await expect(page.locator('.main-content')).toHaveScreenshot('dashboard-command-center.png', {
      animations: 'disabled'
    });
  });

  test('Settings safety hierarchy', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await gotoMockedRenderer(page, '#settings');
    await waitForAppReady(page, '.settings-page');
    await page.locator('.section-detection').scrollIntoViewIfNeeded();
    await expect(page.locator('.main-content')).toHaveScreenshot('settings-safety-hierarchy.png', {
      animations: 'disabled'
    });
  });

  test('Navigation uses buttons while preserving hash history', async ({ page }) => {
    await gotoMockedRenderer(page, '#dashboard');
    await waitForAppReady(page, '.dashboard-profile-hero');

    const settings = page.getByRole('button', { name: 'Settings', exact: true });
    const activity = page.getByRole('button', { name: 'Activity', exact: true });

    await expect(page.locator('.cds--header__name')).toHaveCount(0);
    await expect(page.locator('.cds--side-nav a')).toHaveCount(0);
    await expect(activity).toHaveCSS('display', 'flex');
    await expect(activity).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');

    const alignment = await activity.evaluate((button) => {
      const icon = button.querySelector('.cds--side-nav__icon').getBoundingClientRect();
      const label = button.querySelector('.cds--side-nav__link-text').getBoundingClientRect();
      return Math.abs((icon.top + icon.height / 2) - (label.top + label.height / 2));
    });
    expect(alignment).toBeLessThanOrEqual(1);

    await settings.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#settings$/);
    await expect(settings).toHaveAttribute('aria-current', 'page');

    await activity.click();
    await expect(page).toHaveURL(/#logs$/);
    await page.goBack();
    await expect(page).toHaveURL(/#settings$/);
    await expect(settings).toHaveAttribute('aria-current', 'page');

    const overview = page.getByRole('button', { name: 'Overview', exact: true });
    await overview.focus();
    await page.keyboard.press('Space');
    await expect(page).toHaveURL(/#dashboard$/);
  });

  test('First-run logo is not draggable', async ({ page }) => {
    await gotoMockedRenderer(page, '#dashboard', { appSettings: { firstRunCompleted: false } });
    await expect(page.locator('.first-run-brand-mark')).toBeVisible();
    await expect(page.locator('.first-run-brand-mark')).toHaveAttribute('draggable', 'false');
  });

  test('Settings clamps unsafe numeric values to schema maximums', async ({ page }) => {
    await gotoMockedRenderer(page, '#settings');
    await waitForAppReady(page, '.settings-page');

    const batchSize = page.locator('.field-maintenance_jail_batch_size input');
    const reviewInterval = page.locator('.field-maintenance_jail_interval_ms input');

    await expect(batchSize).toHaveAttribute('max', '64');
    await batchSize.fill('222222');
    await expect(batchSize).toHaveValue('64');

    await expect(reviewInterval).toHaveAttribute('max', '300000');
    await reviewInterval.fill('333333333333330');
    await expect(reviewInterval).toHaveValue('300000');
  });

  for (const language of ['en', 'ru']) {
    test(`Settings cards stay balanced in ${language.toUpperCase()}`, async ({ page }) => {
      await gotoMockedRenderer(page, '#settings', { appSettings: { language } });
      await waitForAppReady(page, '.settings-page');

      for (const width of [980, 1180, 1280, 1440, 1920]) {
        await page.setViewportSize({ width, height: 1080 });
        const geometry = await page.evaluate(() => {
          const detection = document.querySelector('.section-detection').getBoundingClientRect();
          const tuning = document.querySelector('.section-tuning').getBoundingClientRect();
          const specialists = document.querySelector('.section-specialists').getBoundingClientRect();
          return {
            detectionLeft: detection.left,
            detectionWidth: detection.width,
            detectionBottom: detection.bottom,
            tuningLeft: tuning.left,
            tuningTop: tuning.top,
            tuningWidth: tuning.width,
            tuningBottom: tuning.bottom,
            specialistsTop: specialists.top,
            pageWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth
          };
        });

        expect(geometry.detectionLeft).toBe(geometry.tuningLeft);
        expect(geometry.detectionWidth).toBe(geometry.tuningWidth);
        expect(geometry.tuningTop - geometry.detectionBottom).toBe(16);
        expect(geometry.specialistsTop - geometry.tuningBottom).toBe(16);
        expect(geometry.scrollWidth).toBe(geometry.pageWidth);
      }
    });
  }

  test('Topology core map', async ({ page }) => {
    await gotoMockedRenderer(page, '#topology');
    await waitForAppReady(page, '.topology-map');
    await expect(page.locator('.topology-layout')).toHaveScreenshot('topology-core-map.png', {
      animations: 'disabled'
    });
  });

  test('Logs activity viewer', async ({ page }) => {
    await gotoMockedRenderer(page, '#logs');
    await waitForAppReady(page, '.logs-page');
    await expect(page.locator('.log-table tbody tr')).toHaveCount(4);
    await expect(page.locator('.main-content')).toHaveScreenshot('logs-activity-viewer.png', {
      animations: 'disabled',
      // The Last Refresh KPI renders the wall-clock load time.
      mask: [page.locator('.logs-summary-grid .kpi-cell:nth-child(4)')]
    });
  });

  test('Advanced tools MSI viewer', async ({ page }) => {
    await gotoMockedRenderer(page, '#advanced');
    await waitForAppReady(page, '.advanced-tools-page');
    await expect(page.locator('.msi-table tbody tr')).toHaveCount(3);
    await expect(page.locator('.main-content')).toHaveScreenshot('advanced-tools-msi.png', {
      animations: 'disabled'
    });
  });

  test('backend-unavailable Dashboard error state', async ({ page }) => {
    await gotoMockedRenderer(page, '#dashboard', { backendUnavailable: true });
    await waitForAppReady(page, '.dashboard-profile-hero');
    await expect(page.locator('.main-content')).toHaveScreenshot('dashboard-backend-unavailable.png', {
      animations: 'disabled'
    });
  });
});

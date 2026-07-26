const { expect, test } = require('@playwright/test');
const axePlaywright = require('@axe-core/playwright');
const { formatViolations, gotoMockedRenderer, installRendererMock, waitForAppReady } = require('../fixtures/rendererMock');

const AxeBuilder = axePlaywright.default || axePlaywright.AxeBuilder || axePlaywright;

test.beforeEach(() => {
  expect(typeof installRendererMock).toBe('function');
});

async function expectNoA11yViolations(page, selector) {
  await waitForAppReady(page, selector);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(formatViolations(results.violations)).toEqual([]);
}

test.describe('renderer accessibility smoke', () => {
  test('Dashboard has no axe violations', async ({ page }) => {
    await gotoMockedRenderer(page, '#dashboard');
    await expectNoA11yViolations(page, '.dashboard-profile-hero');
  });

  test('Settings has no axe violations', async ({ page }) => {
    await gotoMockedRenderer(page, '#settings');
    await expectNoA11yViolations(page, '.settings-page');
  });

  test('Topology has no axe violations', async ({ page }) => {
    await gotoMockedRenderer(page, '#topology');
    await expectNoA11yViolations(page, '.topology-map');
  });

  test('Logs has no axe violations', async ({ page }) => {
    await gotoMockedRenderer(page, '#logs');
    await expectNoA11yViolations(page, '.logs-page');
  });

  test('Advanced Tools has no axe violations', async ({ page }) => {
    await gotoMockedRenderer(page, '#advanced');
    await expectNoA11yViolations(page, '.advanced-tools-page');
  });
});

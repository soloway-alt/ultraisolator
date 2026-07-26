import assert from 'node:assert/strict';
import test from 'node:test';
import { APP_SETTINGS_PATCH_KEYS, DEFAULT_APP_SETTINGS } from '../shared/app-settings-schema.mjs';
import rendererMock from './fixtures/rendererMock.js';

test('renderer mock app settings mirror the shared schema defaults', () => {
  const expected = {};
  for (const key of APP_SETTINGS_PATCH_KEYS) {
    expected[key] = DEFAULT_APP_SETTINGS[key];
  }
  // The visual mock deliberately marks the first run as completed so visual
  // tests land on the app instead of the first-run wizard.
  expected.firstRunCompleted = true;
  assert.deepEqual(rendererMock.DEFAULT_APP_SETTINGS, expected);
});

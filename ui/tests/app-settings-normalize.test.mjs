import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeAppSettings, normalizeAppSettingsPatch } from '../shared/app-settings-schema.mjs';

const EXPECTED_DEFAULTS = {
  settingsVersion: 3,
  revision: 0,
  language: 'en',
  launchAtWindowsStartup: false,
  minimizeToTrayOnStart: false,
  notificationToastsEnabled: true,
  firstRunCompleted: false
};

test('empty input normalizes to the defaults', () => {
  assert.deepEqual(normalizeAppSettings(), EXPECTED_DEFAULTS);
  assert.deepEqual(normalizeAppSettings({}), EXPECTED_DEFAULTS);
});

test('unknown keys are dropped and settingsVersion is pinned', () => {
  const normalized = normalizeAppSettings({ settingsVersion: 99, startIsolatorAutomatically: true });
  assert.deepEqual(normalized, EXPECTED_DEFAULTS);
  assert.equal('startIsolatorAutomatically' in normalized, false);
});

test('language only accepts en and ru', () => {
  assert.equal(normalizeAppSettings({ language: 'ru' }).language, 'ru');
  assert.equal(normalizeAppSettings({ language: 'en' }).language, 'en');
  assert.equal(normalizeAppSettings({ language: 'fr' }).language, 'en');
  assert.equal(normalizeAppSettings({ language: 'RU' }).language, 'en');
});

test('notificationToastsEnabled defaults to true unless explicitly false', () => {
  assert.equal(normalizeAppSettings({}).notificationToastsEnabled, true);
  assert.equal(normalizeAppSettings({ notificationToastsEnabled: false }).notificationToastsEnabled, false);
  // The idiom is `!== false`, so other falsy values still mean enabled.
  assert.equal(normalizeAppSettings({ notificationToastsEnabled: 0 }).notificationToastsEnabled, true);
  assert.equal(normalizeAppSettings({ notificationToastsEnabled: undefined }).notificationToastsEnabled, true);
});

test('boolean settings are coerced with Boolean()', () => {
  const normalized = normalizeAppSettings({
    launchAtWindowsStartup: 1,
    minimizeToTrayOnStart: 'yes',
    firstRunCompleted: null
  });
  assert.equal(normalized.launchAtWindowsStartup, true);
  assert.equal(normalized.minimizeToTrayOnStart, true);
  assert.equal(normalized.firstRunCompleted, false);
});

test('revision keeps non-negative safe integers and resets everything else', () => {
  assert.equal(normalizeAppSettings({ revision: 7 }).revision, 7);
  assert.equal(normalizeAppSettings({ revision: 0 }).revision, 0);
  assert.equal(normalizeAppSettings({ revision: -1 }).revision, 0);
  assert.equal(normalizeAppSettings({ revision: 1.5 }).revision, 0);
  assert.equal(normalizeAppSettings({ revision: '3' }).revision, 0);
  assert.equal(normalizeAppSettings({ revision: Number.MAX_SAFE_INTEGER }).revision, Number.MAX_SAFE_INTEGER);
});

test('patch normalization keeps only known keys and coerces values', () => {
  assert.deepEqual(normalizeAppSettingsPatch(), {});
  assert.deepEqual(normalizeAppSettingsPatch({ revision: 4, settingsVersion: 9, unknown: true }), {});
  assert.deepEqual(
    normalizeAppSettingsPatch({ language: 'de', notificationToastsEnabled: 0, firstRunCompleted: 'done' }),
    { language: 'en', notificationToastsEnabled: false, firstRunCompleted: true }
  );
  assert.deepEqual(normalizeAppSettingsPatch({ language: 'ru' }), { language: 'ru' });
});

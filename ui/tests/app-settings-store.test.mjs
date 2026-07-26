import assert from 'node:assert/strict';
import test from 'node:test';
import { AppSettingsStore } from '../src/state/AppSettingsStore.mjs';
import {
  normalizeAppSettings as normalizeSettings,
  normalizeAppSettingsPatch as normalizePatch
} from '../shared/app-settings-schema.mjs';

const defaults = {
  settingsVersion: 3,
  revision: 0,
  language: 'en',
  launchAtWindowsStartup: false,
  minimizeToTrayOnStart: false,
  notificationToastsEnabled: true,
  firstRunCompleted: false
};

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('a delayed initial read cannot overwrite a newer language change', async () => {
  const initialRead = deferred();
  const write = deferred();
  const store = new AppSettingsStore({
    initialSettings: defaults,
    load: () => initialRead.promise,
    save: () => write.promise,
    normalizeSettings,
    normalizePatch
  });

  const loading = store.initialize();
  const saving = store.update({ language: 'en' });
  initialRead.resolve({ ...defaults, revision: 1, language: 'ru' });
  await loading;
  assert.equal(store.getSnapshot().settings.language, 'en');

  write.resolve({ ...defaults, revision: 2, language: 'en' });
  await saving;
  assert.equal(store.getSnapshot().settings.language, 'en');
});

test('writes are serialized and only the latest response reconciles the UI', async () => {
  const writes = [];
  const store = new AppSettingsStore({
    initialSettings: defaults,
    load: async () => defaults,
    save: (patch) => {
      const pending = deferred();
      writes.push({ patch, pending });
      return pending.promise;
    },
    normalizeSettings,
    normalizePatch
  });
  await store.initialize();

  const first = store.update({ language: 'ru' });
  const second = store.update({ language: 'en' });
  await Promise.resolve();
  assert.equal(writes.length, 1);
  assert.equal(store.getSnapshot().settings.language, 'en');

  writes[0].pending.resolve({ ...defaults, revision: 1, language: 'ru' });
  await first;
  await Promise.resolve();
  assert.equal(writes.length, 2);
  assert.equal(store.getSnapshot().settings.language, 'en');

  writes[1].pending.resolve({ ...defaults, revision: 2, language: 'en' });
  await second;
  assert.equal(store.getSnapshot().settings.language, 'en');
  assert.equal(store.getSnapshot().settings.revision, 2);
});

test('a failed latest write rolls back to the last committed revision', async () => {
  const store = new AppSettingsStore({
    initialSettings: defaults,
    load: async () => ({ ...defaults, revision: 4, language: 'ru' }),
    save: async () => {
      throw new Error('write failed');
    },
    normalizeSettings,
    normalizePatch
  });
  await store.initialize();

  await assert.rejects(store.update({ language: 'en' }), /write failed/);
  assert.equal(store.getSnapshot().settings.language, 'ru');
  assert.equal(store.getSnapshot().settings.revision, 4);
});

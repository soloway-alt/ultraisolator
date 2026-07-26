import { APP_SETTINGS_STORAGE_KEY } from '../constants/settings.mjs';
import {
  DEFAULT_APP_SETTINGS,
  normalizeAppSettings,
  normalizeAppSettingsPatch
} from '../../shared/app-settings-schema.mjs';

// Normalization lives in the shared schema so the renderer cannot drift from
// the Electron main process; re-exported here for renderer callers.
export { normalizeAppSettings, normalizeAppSettingsPatch };

export function loadLocalAppSettings() {
  try {
    const raw = window.localStorage.getItem(APP_SETTINGS_STORAGE_KEY);
    return normalizeAppSettings({ ...DEFAULT_APP_SETTINGS, ...JSON.parse(raw || '{}') });
  } catch (_error) {
    return { ...DEFAULT_APP_SETTINGS };
  }
}

export async function loadAppSettings() {
  if (window.isolator?.getAppSettings) {
    return normalizeAppSettings(await window.isolator.getAppSettings());
  }
  return loadLocalAppSettings();
}

export async function saveAppSettings(patch) {
  const normalizedPatch = normalizeAppSettingsPatch(patch);
  if (window.isolator?.updateAppSettings) {
    return normalizeAppSettings(await window.isolator.updateAppSettings(normalizedPatch));
  }
  const saved = normalizeAppSettings({ ...loadLocalAppSettings(), ...normalizedPatch });
  window.localStorage.setItem(APP_SETTINGS_STORAGE_KEY, JSON.stringify(saved));
  return saved;
}

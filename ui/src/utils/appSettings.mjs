import {
  APP_SETTINGS_KEYS,
  APP_SETTINGS_STORAGE_KEY,
  APP_SETTINGS_VERSION,
  DEFAULT_APP_SETTINGS
} from '../constants/settings.mjs';

export function normalizeAppSettings(settings = {}) {
  const language = settings.language === 'ru' ? 'ru' : 'en';
  return {
    settingsVersion: APP_SETTINGS_VERSION,
    revision: Number.isSafeInteger(settings.revision) && settings.revision >= 0 ? settings.revision : 0,
    language,
    launchAtWindowsStartup: Boolean(settings.launchAtWindowsStartup),
    minimizeToTrayOnStart: Boolean(settings.minimizeToTrayOnStart),
    notificationToastsEnabled: settings.notificationToastsEnabled !== false,
    firstRunCompleted: Boolean(settings.firstRunCompleted)
  };
}

export function normalizeAppSettingsPatch(patch = {}) {
  const normalized = {};
  for (const key of APP_SETTINGS_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(patch, key)) {
      continue;
    }
    normalized[key] = key === 'language'
      ? (patch[key] === 'ru' ? 'ru' : 'en')
      : Boolean(patch[key]);
  }
  return normalized;
}

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

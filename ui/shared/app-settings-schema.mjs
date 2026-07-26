// Single canonical definition of the persisted app-settings shape, shared by
// the Electron main process (settings store + IPC patch validation) and the
// renderer (localStorage fallback + optimistic patch coercion).
// Loaded from CommonJS via synchronous require(esm) in electron-main.js and
// via import in ui/src (re-exported through src/constants/settings.mjs and
// src/utils/appSettings.mjs).

export const APP_SETTINGS_VERSION = 3;

export const DEFAULT_APP_SETTINGS = Object.freeze({
  settingsVersion: APP_SETTINGS_VERSION,
  revision: 0,
  language: 'en',
  launchAtWindowsStartup: false,
  minimizeToTrayOnStart: false,
  notificationToastsEnabled: true,
  firstRunCompleted: false
});

export const APP_SETTINGS_PATCH_KEYS = Object.freeze([
  'language',
  'launchAtWindowsStartup',
  'minimizeToTrayOnStart',
  'notificationToastsEnabled',
  'firstRunCompleted'
]);

const PATCH_KEY_SET = new Set(APP_SETTINGS_PATCH_KEYS);

// Normalizes a full settings object read from disk (main) or localStorage
// (renderer fallback). NOTE the deliberate asymmetry with the patch
// normalizer below: notificationToastsEnabled uses the `!== false` idiom, so
// any value other than an explicit `false` (including 0, null, undefined)
// means "enabled". Stored settings predate strict validation and must default
// toward showing toasts.
export function normalizeAppSettings(candidate = {}) {
  const language = candidate.language === 'ru' ? 'ru' : 'en';
  return {
    settingsVersion: APP_SETTINGS_VERSION,
    revision: Number.isSafeInteger(candidate.revision) && candidate.revision >= 0 ? candidate.revision : 0,
    language,
    launchAtWindowsStartup: Boolean(candidate.launchAtWindowsStartup),
    minimizeToTrayOnStart: Boolean(candidate.minimizeToTrayOnStart),
    notificationToastsEnabled: candidate.notificationToastsEnabled !== false,
    firstRunCompleted: Boolean(candidate.firstRunCompleted)
  };
}

// Renderer-side patch coercion: keeps only known keys and coerces boolean
// fields with Boolean(), so `{notificationToastsEnabled: 0}` becomes `false`
// here while normalizeAppSettings above would treat the same value as `true`.
// A patch expresses fresh user intent, so truthiness coercion is correct;
// keep both behaviors as-is.
export function normalizeAppSettingsPatch(patch = {}) {
  const normalized = {};
  for (const key of APP_SETTINGS_PATCH_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(patch, key)) {
      continue;
    }
    normalized[key] = key === 'language'
      ? (patch[key] === 'ru' ? 'ru' : 'en')
      : Boolean(patch[key]);
  }
  return normalized;
}

// Main-process patch validation at the IPC trust boundary: unlike the
// renderer coercion above, this rejects unknown keys and non-boolean values
// outright instead of silently fixing them.
export function validateAppSettingsPatch(patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
    throw new TypeError('App settings patch must be an object.');
  }
  const validatedPatch = {};
  for (const [key, value] of Object.entries(patch)) {
    if (!PATCH_KEY_SET.has(key)) {
      throw new TypeError(`Unsupported app setting: ${key}`);
    }
    if (key === 'language') {
      if (value !== 'en' && value !== 'ru') {
        throw new TypeError('language must be en or ru.');
      }
    } else if (typeof value !== 'boolean') {
      throw new TypeError(`${key} must be a boolean.`);
    }
    validatedPatch[key] = value;
  }
  return validatedPatch;
}

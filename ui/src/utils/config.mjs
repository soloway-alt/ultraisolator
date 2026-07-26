import { FIELD_LABELS } from '../constants/settings.mjs';

export const EMPTY_APP_PROFILE = {
  exe: '',
  enabled: true,
  treat_as_game: false,
  never_jail: false,
  always_jail: false,
  priority_class: ''
};

export function fieldLabel(field) {
  return FIELD_LABELS[field] || field;
}

function validationError(key, fallback, params = {}, field = null) {
  return { key: `validation.${key}`, fallback, params, field };
}

// Renders a structured notice ({key, fallback, params, field?}) through the
// catalog; plain strings pass through untouched.
export function translatedNotice(notice, t) {
  if (!notice || typeof notice === 'string') {
    return notice;
  }
  const params = { ...(notice.params || {}) };
  if (notice.field) {
    params.field = t(`field.${notice.field}`, fieldLabel(notice.field));
  }
  return t(notice.key, notice.fallback, params);
}

export function parseListValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  return String(value || '')
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function toEditableConfig(config = {}, schema = {}) {
  const draft = {};
  for (const field of Object.keys(schema)) {
    const value = config[field];
    if (schema[field].type === 'app_profiles') {
      draft[field] = Array.isArray(value) ? value.map((profile) => ({ ...EMPTY_APP_PROFILE, ...profile })) : [];
    } else {
      draft[field] = Array.isArray(value) ? value.join('\n') : value ?? '';
    }
  }
  return draft;
}

// Single definition of the implicit `app_profiles[i]` / `app_profiles[i].field`
// error-key format shared by the validator below and AppProfilesEditor.
export function appProfileFieldKey(index, field = null) {
  return field ? `app_profiles[${index}].${field}` : `app_profiles[${index}]`;
}

export function validateAppProfilesDraft(value, spec = {}) {
  const profiles = [];
  const errors = {};
  const seen = new Set();
  const priorityChoices = spec.priority_choices || [];
  if (!Array.isArray(value)) {
    errors.app_profiles = validationError('profileList', 'App-specific rules must be a list.');
    return { profiles, errors };
  }

  value.forEach((item, index) => {
    const profile = { ...EMPTY_APP_PROFILE, ...(item || {}) };
    const exe = String(profile.exe || '').trim().toLowerCase();
    if (!exe) {
      errors[appProfileFieldKey(index, 'exe')] = validationError('executableRequired', 'Application executable is required.');
    } else if (seen.has(exe)) {
      errors[appProfileFieldKey(index, 'exe')] = validationError('duplicateExecutable', 'Duplicate application executable: {{exe}}.', { exe });
    }
    seen.add(exe);

    const priority = String(profile.priority_class || '').trim().toLowerCase();
    if (priority && !priorityChoices.includes(priority)) {
      errors[appProfileFieldKey(index, 'priority_class')] = validationError('priorityChoice', 'Priority must be one of: {{choices}}.', { choices: priorityChoices.join(', ') });
    }
    if (profile.never_jail && profile.always_jail) {
      errors[appProfileFieldKey(index)] = validationError('profileRuleConflict', 'Choose either “Always leave unchanged” or “Always limit in background”.');
    }

    profiles.push({
      exe,
      enabled: Boolean(profile.enabled),
      treat_as_game: Boolean(profile.treat_as_game),
      never_jail: Boolean(profile.never_jail),
      always_jail: Boolean(profile.always_jail),
      priority_class: priority
    });
  });

  return { profiles, errors };
}

export function validateConfigDraft(draft, schema) {
  const config = {};
  const errors = {};
  for (const [field, spec] of Object.entries(schema || {})) {
    const value = draft[field];
    if (spec.type === 'bool') {
      config[field] = Boolean(value);
      continue;
    }
    if (spec.type === 'string_list') {
      config[field] = parseListValue(value);
      continue;
    }
    if (spec.type === 'app_profiles') {
      const validation = validateAppProfilesDraft(value, spec);
      config[field] = validation.profiles;
      Object.assign(errors, validation.errors);
      continue;
    }
    if (spec.type === 'string') {
      config[field] = String(value || '');
      continue;
    }
    if (spec.type === 'choice') {
      const selected = String(value || '').trim().toLowerCase();
      if (!spec.choices.includes(selected)) {
        errors[field] = validationError('choice', '{{field}} must be one of: {{choices}}.', { choices: spec.choices.join(', ') }, field);
      } else {
        config[field] = selected;
      }
      continue;
    }
    if (spec.type === 'int' || spec.type === 'float') {
      const text = String(value).trim();
      if (!text) {
        errors[field] = validationError('required', '{{field}} is required.', {}, field);
        continue;
      }
      const numeric = Number(text);
      if (!Number.isFinite(numeric)) {
        errors[field] = validationError('number', '{{field}} must be a number.', {}, field);
        continue;
      }
      if (spec.type === 'int' && !Number.isInteger(numeric)) {
        errors[field] = validationError('integer', '{{field}} must be a whole number.', {}, field);
        continue;
      }
      if (typeof spec.min === 'number' && numeric < spec.min) {
        errors[field] = validationError('minimum', '{{field}} must be at least {{min}}.', { min: spec.min }, field);
        continue;
      }
      if (typeof spec.max === 'number' && numeric > spec.max) {
        errors[field] = validationError('maximum', '{{field}} must be no more than {{max}}.', { max: spec.max }, field);
        continue;
      }
      config[field] = numeric;
    }
  }
  return { config, errors };
}

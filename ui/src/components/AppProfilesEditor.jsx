import { Tile } from '@carbon/react';
import { EMPTY_APP_PROFILE, appProfileFieldKey, translatedNotice } from '../utils/config.mjs';

// The App-specific rules CRUD editor, extracted from Settings.jsx. The
// profiles live in the parent's draft and the validation errors in the
// parent's fieldErrors map; the editor reports whole next values through
// onProfilesChange/onFieldErrorsChange instead of reaching into the
// parent's setState pairs.
/** @param {{profiles: object[], spec: import('../types.js').ConfigFieldSpec, fieldErrors: object, onProfilesChange: (profiles: object[]) => void, onFieldErrorsChange: (errors: object) => void, t: Function}} props */
export function AppProfilesEditor({ profiles, spec, fieldErrors, onProfilesChange, onFieldErrorsChange, t }) {
  const appProfileErrors = (index, field = null) => (
    translatedNotice(fieldErrors[appProfileFieldKey(index, field)], t) || ''
  );

  const addProfile = () => {
    onProfilesChange([...profiles, { ...EMPTY_APP_PROFILE }]);
  };

  const removeProfile = (index) => {
    onProfilesChange(profiles.filter((_, itemIndex) => itemIndex !== index));
    // Indices shift on removal, so drop every app_profiles[...] error instead
    // of renumbering; the next validation pass rebuilds them.
    const next = {};
    for (const [key, value] of Object.entries(fieldErrors)) {
      if (!key.startsWith('app_profiles[')) {
        next[key] = value;
      }
    }
    onFieldErrorsChange(next);
  };

  const updateProfile = (index, patch) => {
    onProfilesChange(profiles.map((profile, itemIndex) => (
      itemIndex === index ? { ...profile, ...patch } : profile
    )));
  };

  return (
    <Tile className="settings-section profiles-editor">
      <div className="profiles-header">
        <div>
          <div className="module-title">{t('settings.profiles', 'App-specific rules')}</div>
          <div className="profiles-subtitle">{t('settings.profilesDetail', 'Choose how individual apps are handled. System and anti-cheat processes always stay protected.')}</div>
        </div>
        <button type="button" onClick={addProfile}>{t('settings.addProfile', 'Add profile')}</button>
      </div>
      {profiles.length === 0 ? (
        <div className="module-empty">{t('settings.noProfiles', 'No profiles configured')}</div>
      ) : (
        <div className="profiles-list">
          {profiles.map((profile, index) => (
            <div className="profile-row" key={`${profile.exe || 'profile'}-${index}`}>
              <label className={`settings-field${appProfileErrors(index, 'exe') ? ' invalid' : ''}`}>
                <span className="settings-field-label">{t('settings.profileExecutable', 'Application executable')}</span>
                <input
                  type="text"
                  value={profile.exe}
                  spellCheck="false"
                  placeholder="example.exe"
                  onChange={(event) => updateProfile(index, { exe: event.target.value })}
                />
                <span className={appProfileErrors(index, 'exe') ? 'settings-field-error' : 'settings-field-hint'}>
                  {appProfileErrors(index, 'exe') || t('settings.profileExeHint', 'Names without .exe are completed automatically.')}
                </span>
              </label>
              <label className="settings-field">
                <span className="settings-field-label">{t('settings.priority', 'Priority')}</span>
                <select
                  value={profile.priority_class}
                  onChange={(event) => updateProfile(index, { priority_class: event.target.value })}
                >
                  <option value="">{t('settings.default', 'Default')}</option>
                  {spec.priority_choices.map((choice) => (
                    <option key={choice} value={choice}>{choice}</option>
                  ))}
                </select>
                <span className={appProfileErrors(index, 'priority_class') ? 'settings-field-error' : 'settings-field-hint'}>
                  {appProfileErrors(index, 'priority_class') || t('settings.priorityHint', 'Optional priority override.')}
                </span>
              </label>
              <div className="profile-flags">
                {[
                  ['enabled', t('settings.profileEnabled', 'Enabled')],
                  ['treat_as_game', t('settings.profileTreatAsGame', 'Treat as game')],
                  ['never_jail', t('settings.profileNeverJail', 'Always leave unchanged')],
                  ['always_jail', t('settings.profileAlwaysJail', 'Always limit in background')]
                ].map(([field, label]) => (
                  <label className="profile-flag" key={field}>
                    <input
                      type="checkbox"
                      checked={Boolean(profile[field])}
                      onChange={(event) => updateProfile(index, { [field]: event.target.checked })}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              {appProfileErrors(index) ? <div className="settings-field-error profile-row-error">{appProfileErrors(index)}</div> : null}
              <button type="button" className="profile-remove" onClick={() => removeProfile(index)}>{t('settings.remove', 'Remove')}</button>
            </div>
          ))}
        </div>
      )}
    </Tile>
  );
}

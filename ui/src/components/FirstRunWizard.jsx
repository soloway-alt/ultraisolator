import { useEffect, useRef, useState } from 'react';
import brandLogo from '../../assets/icon.png';
import { CONFIG_PRESETS } from '../constants/settings.js';
import { useI18n } from '../i18n.jsx';
import { useAppSettings } from '../state/AppSettingsContext.jsx';
import { requestJson } from '../utils/api.js';

const STEP_COUNT = 3;

export function FirstRunWizard({ live }) {
  const { t } = useI18n();
  const { settings, ready: settingsReady, updateSettings } = useAppSettings();
  const [step, setStep] = useState(1);
  const [selectedPresetId, setSelectedPresetId] = useState('competitive');
  const [reviewConfig, setReviewConfig] = useState(null);
  const [configApplied, setConfigApplied] = useState(false);
  const [busyPreset, setBusyPreset] = useState(null);
  const [error, setError] = useState('');
  const panelRef = useRef(null);
  const previousFocusRef = useRef(null);

  const isOpen = settingsReady && !settings.firstRunCompleted;

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    previousFocusRef.current = document.activeElement;
    return () => {
      previousFocusRef.current?.focus?.();
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => {
      panelRef.current?.querySelector('#first-run-title')?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, step]);

  if (!isOpen) {
    return null;
  }

  const selectedPreset = CONFIG_PRESETS.find((preset) => preset.id === selectedPresetId) || CONFIG_PRESETS[0];
  const status = live?.snapshot?.status || {};
  const connectionState = live?.connectionState || 'idle';
  const adminKnown = typeof status.admin === 'boolean';
  const recoveryKnown = connectionState === 'connected' && Boolean(live?.snapshot);
  const recoveryReady = recoveryKnown
    && !status.persistent_recovery_incomplete
    && Number(status.reported_failure_count || 0) === 0;
  const isBusy = Boolean(busyPreset);

  const completeFirstRun = async (patch = {}) => {
    await updateSettings({ ...patch, firstRunCompleted: true });
  };

  const skipFirstRun = async () => {
    setBusyPreset('skip');
    setError('');
    try {
      await completeFirstRun();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('firstRun.skipError', 'Unable to skip setup'));
    } finally {
      setBusyPreset(null);
    }
  };

  const prepareReview = async () => {
    setBusyPreset('review');
    setError('');
    setConfigApplied(false);
    try {
      const [defaultsPayload, configPayload] = await Promise.all([
        requestJson('/api/config/defaults'),
        requestJson('/api/config')
      ]);
      setReviewConfig({
        ...defaultsPayload.defaults,
        ...configPayload.config,
        ...selectedPreset.config
      });
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('firstRun.reviewError', 'Unable to prepare configuration review'));
    } finally {
      setBusyPreset(null);
    }
  };

  const applyPreset = async (preset) => {
    setBusyPreset(preset.id);
    setError('');
    try {
      if (!configApplied) {
        await requestJson('/api/config', {
          method: 'PUT',
          body: JSON.stringify({ config: reviewConfig })
        });
        setConfigApplied(true);
      }
      try {
        await completeFirstRun();
      } catch (err) {
        setError(t('firstRun.completionError', 'Profile applied, but setup completion could not be saved. Retry to finish setup.'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('firstRun.applyError', 'Unable to apply preset'));
    } finally {
      setBusyPreset(null);
    }
  };

  const moveToStep = (nextStep) => {
    setError('');
    if (nextStep < STEP_COUNT) {
      setConfigApplied(false);
    }
    setStep(nextStep);
  };

  const handleDialogKeyDown = (event) => {
    if (event.key === 'Escape' && !isBusy) {
      event.preventDefault();
      skipFirstRun();
      return;
    }
    if (event.key !== 'Tab') {
      return;
    }
    const focusable = panelRef.current?.querySelectorAll('button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])');
    if (!focusable?.length) {
      event.preventDefault();
      panelRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const title = panelRef.current?.querySelector('#first-run-title');
    if (event.shiftKey && (document.activeElement === first || document.activeElement === title)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const presetLabel = (preset) => t(`settings.preset.${preset.id}.label`, preset.label);
  const presetDetail = (preset) => t(`settings.preset.${preset.id}.detail`, preset.detail);

  const stepContent = step === 1 ? (
    <>
      <div className="first-run-heading">
        <div className="first-run-kicker">{t('firstRun.kicker', 'First run')}</div>
        <h2 id="first-run-title" tabIndex="-1">{t('firstRun.readinessTitle', 'Ready for cleaner frame delivery')}</h2>
        <p id="first-run-description">
          {t('firstRun.readinessDetail', 'UltraIsolator checks game monitoring and safe restore before you choose a session profile.')}
        </p>
      </div>
      <div className="first-run-readiness" aria-label={t('firstRun.readinessLabel', 'System readiness')}>
        <article className={`first-run-check ${connectionState === 'connected' ? 'ready' : 'attention'}`}>
          <span>{t('firstRun.localEngine', 'Local monitoring')}</span>
          <strong>{connectionState === 'connected' ? t('firstRun.connected', 'Connected') : t(`connection.${connectionState}`, connectionState)}</strong>
          <small>{t('firstRun.localEngineDetail', 'Your configuration and controls stay on this PC.')}</small>
        </article>
        <article className={`first-run-check ${status.admin ? 'ready' : 'attention'}`}>
          <span>{t('firstRun.adminAccess', 'Administrator access')}</span>
          <strong>{adminKnown ? (status.admin ? t('dashboard.yes', 'Yes') : t('dashboard.no', 'No')) : t('firstRun.checking', 'Checking')}</strong>
          <small>{t('firstRun.adminDetail', 'Required for CPU, power-plan, and process controls.')}</small>
        </article>
        <article className={`first-run-check ${recoveryReady ? 'ready' : 'attention'}`}>
          <span>{t('firstRun.recovery', 'Recovery')}</span>
          <strong>{!recoveryKnown
            ? t('firstRun.checking', 'Checking')
            : recoveryReady
              ? t('firstRun.available', 'Available')
              : t('firstRun.recoveryNeedsReview', 'Needs review')}</strong>
          <small>{!recoveryKnown
            ? t('firstRun.recoveryCheckingDetail', 'Waiting for the local recovery status.')
            : recoveryReady
              ? t('firstRun.recoveryDetail', 'You can restore the protected system state from the dashboard.')
              : t('firstRun.recoveryAttentionDetail', 'Resolve the reported recovery state before starting a session.')}</small>
        </article>
      </div>
      <div className="first-run-note">
        <strong>{t('firstRun.safeByDesign', 'Safe by design')}</strong>
        <span>{t('firstRun.safeByDesignDetail', 'Steam, FACEIT, anti-cheat, and Windows system processes remain protected.')}</span>
      </div>
    </>
  ) : step === 2 ? (
    <>
      <div className="first-run-heading">
        <div className="first-run-kicker">{t('firstRun.presetKicker', 'Choose your setup')}</div>
        <h2 id="first-run-title" tabIndex="-1">{t('firstRun.title', 'Choose a config preset')}</h2>
        <p id="first-run-description">{t('firstRun.presetDetail', 'Start with a safe profile. Every setting remains editable later.')}</p>
      </div>
      <div className="first-run-grid" aria-label={t('firstRun.presetList', 'Configuration presets')}>
        {CONFIG_PRESETS.map((preset) => {
          const selected = preset.id === selectedPreset.id;
          return (
            <button
              type="button"
              className={`first-run-preset${selected ? ' selected' : ''}`}
              key={preset.id}
              aria-pressed={selected}
              disabled={isBusy}
              onClick={() => {
                setSelectedPresetId(preset.id);
                setReviewConfig(null);
                setConfigApplied(false);
              }}
            >
              <span className="first-run-preset-topline">
                <span>{presetLabel(preset)}</span>
                {preset.id === 'competitive' ? <small>{t('firstRun.recommended', 'Recommended')}</small> : null}
              </span>
              <small>{presetDetail(preset)}</small>
            </button>
          );
        })}
      </div>
    </>
  ) : (
    <>
      <div className="first-run-heading">
        <div className="first-run-kicker">{t('firstRun.reviewKicker', 'Review before apply')}</div>
        <h2 id="first-run-title" tabIndex="-1">{t('firstRun.reviewTitle', 'Confirm your session profile')}</h2>
        <p id="first-run-description">{presetDetail(selectedPreset)}</p>
      </div>
      <div className="first-run-review">
        <div className="first-run-review-profile">
          <span>{t('firstRun.selectedProfile', 'Selected profile')}</span>
          <strong>{presetLabel(selectedPreset)}</strong>
        </div>
        <dl className="first-run-review-list">
          <div>
            <dt>{t('firstRun.activePolling', 'Game detection response')}</dt>
            <dd>{reviewConfig?.poll_interval_active_ms} ms</dd>
          </div>
          <div>
            <dt>{t('firstRun.backgroundControl', 'Background control')}</dt>
            <dd>{reviewConfig?.enable_background_jailing ? t('common.enabled', 'Enabled') : t('common.disabled', 'Disabled')}</dd>
          </div>
          <div>
            <dt>{t('firstRun.antiCheatPolicy', 'Anti-cheat policy')}</dt>
            <dd>{t(`antiCheat.${reviewConfig?.anti_cheat_mode}`, reviewConfig?.anti_cheat_mode)}</dd>
          </div>
          <div>
            <dt>{t('firstRun.housekeeping', 'Windows CPU reserve')}</dt>
            <dd>{reviewConfig?.housekeeping_cores}</dd>
          </div>
          <div>
            <dt>{t('firstRun.batchSize', 'Background apps per pass')}</dt>
            <dd>{reviewConfig?.maintenance_jail_batch_size}</dd>
          </div>
          <div>
            <dt>{t('firstRun.batchInterval', 'Background review interval')}</dt>
            <dd>{reviewConfig?.maintenance_jail_interval_ms} ms</dd>
          </div>
          <div>
            <dt>{t('firstRun.batchCooldown', 'Pause between background passes')}</dt>
            <dd>{reviewConfig?.maintenance_jail_batch_cooldown_ms} ms</dd>
          </div>
        </dl>
        <p className="first-run-review-note">
          {t('firstRun.reviewNote', 'The profile is saved after validation. Game monitoring starts automatically and remains fully reversible.')}
        </p>
      </div>
    </>
  );

  return (
    <div
      className="first-run-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="first-run-title"
      aria-describedby="first-run-description"
      aria-busy={isBusy}
      onKeyDown={handleDialogKeyDown}
    >
      <div className="first-run-panel" ref={panelRef} tabIndex="-1">
        <aside className="first-run-aside" aria-label={t('firstRun.setupProgress', 'Setup progress')}>
          <div className="first-run-brand">
            <img className="first-run-brand-mark" src={brandLogo} alt="" draggable={false} />
            <span>
              <strong>{t('app.brand', 'UltraIsolator')}</strong>
              <small>{t('firstRun.brandDetail', 'Competitive session control')}</small>
            </span>
          </div>
          <ol className="first-run-progress">
            {[
              t('firstRun.stepReadiness', 'Readiness'),
              t('firstRun.stepPreset', 'Profile'),
              t('firstRun.stepReview', 'Review')
            ].map((label, index) => {
              const stepNumber = index + 1;
              return (
                <li key={label} className={stepNumber === step ? 'active' : stepNumber < step ? 'complete' : ''} aria-current={stepNumber === step ? 'step' : undefined}>
                  <span>{String(stepNumber).padStart(2, '0')}</span>
                  <strong>{label}</strong>
                </li>
              );
            })}
          </ol>
          <div className="first-run-aside-note">
            <span>{t('firstRun.stepCount', 'Step {{step}} of {{count}}').replace('{{step}}', step).replace('{{count}}', STEP_COUNT)}</span>
            <strong>{t('firstRun.localReversible', 'Local. Reversible. Transparent.')}</strong>
          </div>
        </aside>

        <div className="first-run-stage">
          {stepContent}
          {error ? <div className="action-error" role="alert">{error}</div> : null}
          <div className="first-run-actions">
            <button type="button" className="first-run-skip" disabled={isBusy} aria-keyshortcuts="Escape" onClick={skipFirstRun}>
              {t('firstRun.skip', 'Skip for now')}
            </button>
            <div className="first-run-actions-primary">
              {step > 1 ? (
                <button type="button" disabled={isBusy} onClick={() => moveToStep(step - 1)}>
                  {t('common.back', 'Back')}
                </button>
              ) : null}
              {step < STEP_COUNT ? (
                <button type="button" className="primary" disabled={isBusy} onClick={() => (step === 1 ? moveToStep(2) : prepareReview())}>
                  {step === 1
                    ? t('firstRun.continue', 'Continue')
                    : isBusy
                      ? t('firstRun.reviewing', 'Preparing review')
                      : t('firstRun.review', 'Review setup')}
                </button>
              ) : (
                <button type="button" className="primary" disabled={isBusy || !reviewConfig} onClick={() => applyPreset(selectedPreset)}>
                  {isBusy
                    ? t('firstRun.applying', 'Applying {{preset}}').replace('{{preset}}', presetLabel(selectedPreset))
                    : t('firstRun.apply', 'Apply profile')}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useMemo } from 'react';
import { Tag, Tile } from '@carbon/react';
import { useBackendResource } from '../hooks/useBackendResource.js';
import { translatedNotice } from '../utils/config.mjs';
import { useI18n } from '../i18n.jsx';

const CORE_CHECK_ORDER = [
  'configured_games',
  'admin',
  'engine_running',
  'power_plan',
  'timer_resolution',
  'background_jailing',
  'ifeo_priority',
  'topology',
  'recovery'
];
const STATUS_ORDER = { error: 0, warning: 1, ok: 2, info: 3 };

function checkTone(status) {
  if (status === 'ok') {
    return 'green';
  }
  if (status === 'error') {
    return 'red';
  }
  if (status === 'info') {
    return 'gray';
  }
  return 'yellow';
}

function checkOrder(check) {
  const index = CORE_CHECK_ORDER.indexOf(check.id);
  return index === -1 ? CORE_CHECK_ORDER.length : index;
}

function statusLabel(status, t) {
  return t(`checkStatus.${status}`, status);
}

function checkLabel(check, t) {
  return t(`readiness.check.${check.id}.label`, check.label);
}

function checkDetail(check, t) {
  return t(`readiness.check.${check.id}.${check.status}`, check.detail, check.data || {});
}

export function ReadinessChecklist({ live }) {
  const { t } = useI18n();
  const gameMode = Boolean(live.snapshot?.status?.game_mode);
  const hiddenWindow = !live.visible && !gameMode;
  const enabled = live.visible && !gameMode;
  const state = useBackendResource('/api/readiness', {
    enabled,
    refreshPath: '/api/readiness?refresh=1'
  });
  // The paused panel must not show stale checks: while disabled the payload
  // reads as absent, matching the old machine that cleared it on bail.
  const payload = enabled ? state.data : null;

  const summary = payload?.summary || {};
  const topChecks = useMemo(() => {
    const checks = Array.isArray(payload?.checks) ? payload.checks : [];
    return [...checks].sort((left, right) => (
      (STATUS_ORDER[left.status] ?? 3) - (STATUS_ORDER[right.status] ?? 3)
      || checkOrder(left) - checkOrder(right)
    )).slice(0, 9);
  }, [payload?.checks]);
  const nextAction = topChecks.find((check) => check.status === 'error')
    || topChecks.find((check) => check.status === 'warning');

  return (
    <Tile className="module-surface readiness-panel">
      <div className="analysis-header">
        <div>
          <div className="module-title">{t('readiness.title', 'Game readiness')}</div>
          <div className="analysis-subtitle">
            {payload?.available
              ? nextAction
                ? t('readiness.nextAction', 'Next: {{action}}', { action: checkLabel(nextAction, t) })
                : t('readiness.readyCount', '{{ok}}/{{total}} checks ready', { ok: summary.ok || 0, total: summary.total || 0 })
              : gameMode
                ? t('readiness.pausedGame', 'Readiness checks pause while a game is active')
                : hiddenWindow
                  ? t('readiness.pausedHidden', 'Readiness checks pause while the window is hidden')
                  : state.loading
                    ? t('readiness.loading', 'Loading readiness')
                    : t('readiness.unavailable', 'Readiness details are temporarily unavailable')}
          </div>
        </div>
        <div className="analysis-actions">
          <button type="button" onClick={state.reload} disabled={gameMode || state.loading || state.refreshing}>
            {state.refreshing ? t('common.refreshing', 'Refreshing') : t('common.refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {gameMode ? <div className="settings-message">{t('readiness.pausedGame', 'Readiness checks paused during game mode')}</div> : null}
      {hiddenWindow ? <div className="settings-message">{t('readiness.pausedHidden', 'Readiness checks paused while the window is hidden')}</div> : null}
      {state.error ? <div className="action-error">{translatedNotice(state.error, t)}</div> : null}

      <div className="readiness-summary">
        <div>
          <span>{t('checkStatus.ok', 'Ready')}</span>
          <strong>{summary.ok ?? 0}</strong>
        </div>
        <div>
          <span>{t('checkStatus.warning', 'Review')}</span>
          <strong>{summary.warning ?? 0}</strong>
        </div>
        <div>
          <span>{t('checkStatus.error', 'Action required')}</span>
          <strong>{summary.error ?? 0}</strong>
        </div>
      </div>

      <div className="readiness-check-list" aria-label={t('readiness.checkList', 'Game readiness checks')}>
        {topChecks.length ? topChecks.map((check) => (
          <article key={check.id} className={`readiness-check ${check.status}`}>
            <div className="readiness-check-top">
              <strong>{checkLabel(check, t)}</strong>
              <Tag type={checkTone(check.status)}>{statusLabel(check.status, t)}</Tag>
            </div>
            <div className="readiness-check-detail">{checkDetail(check, t)}</div>
          </article>
        )) : (
          <div className="module-empty">{state.loading ? t('readiness.loading', 'Loading readiness') : t('readiness.empty', 'No readiness checks available')}</div>
        )}
      </div>
    </Tile>
  );
}

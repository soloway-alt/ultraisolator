import { useMemo } from 'react';
import { Tag, Tile } from '@carbon/react';
import { useBackendResource } from '../hooks/useBackendResource.js';
import { translatedNotice } from '../utils/config.mjs';
import { useI18n } from '../i18n.jsx';

function checkTone(status) {
  if (status === 'ok') {
    return 'green';
  }
  if (status === 'error') {
    return 'red';
  }
  if (status === 'warning') {
    return 'yellow';
  }
  return 'gray';
}

function statusLabel(status, t) {
  return t(`checkStatus.${status}`, status);
}

function categoryLabel(category, t) {
  return t(`analysis.category.${category}`, category);
}

function checkLabel(check, t) {
  return t(`analysis.check.${check.id}.label`, check.label);
}

function checkDetail(check, t) {
  return t(`analysis.check.${check.id}.${check.status}`, check.detail, check.data || {});
}

export function SystemAnalysis({ live }) {
  const { t } = useI18n();
  const status = live.snapshot?.status || {};
  const gameMode = Boolean(status.game_mode);
  const hiddenWindow = !live.visible && !gameMode;
  const enabled = live.visible && !gameMode;
  // Refetch only on coarse transitions: enabled covers game mode and window
  // visibility, refreshKey covers engine start/stop. Finer status flips
  // (admin, timer, power plan, topology) stay with the manual Refresh button
  // instead of fanning out an /api/analysis request per live tick.
  const analysisResource = useBackendResource('/api/analysis', {
    enabled,
    refreshKey: Boolean(status.running)
  });
  const pausedAnalysis = useMemo(() => ({
    ok: true,
    available: false,
    mode: 'analysis',
    reason: gameMode ? 'paused_in_game_mode' : 'paused_window_hidden',
    score: null,
    grade: 'paused',
    summary: gameMode
      ? t('analysis.pausedGame', 'Analysis paused during game mode.')
      : t('analysis.pausedHidden', 'Analysis paused while the window is hidden.'),
    categories: [],
    checks: []
  }), [gameMode, t]);
  const analysis = enabled ? analysisResource.data : pausedAnalysis;
  const analysisState = analysisResource;

  const score = analysis?.score ?? 0;
  const checks = Array.isArray(analysis?.checks) ? analysis.checks : [];
  const categories = Array.isArray(analysis?.categories) && analysis.categories.length
    ? analysis.categories
    : ['Control plane', 'CPU isolation', 'Latency tuning', 'System health'];
  const goodChecks = checks.filter((check) => check.status === 'ok').length;
  const warningChecks = checks.filter((check) => check.status === 'warning').length + checks.filter((check) => check.status === 'error').length;
  const summaryText = analysis?.available
    ? t(`analysis.summary.${analysis?.grade}`, analysis?.summary || 'System readiness analysis')
    : analysis?.summary || (analysisState.loading
      ? t('analysis.loading', 'Loading setup quality')
      : t('analysis.unavailable', 'Setup quality is temporarily unavailable'));
  const gradeText = t(`analysis.grade.${analysis?.grade}`, analysis?.grade || 'not scored');

  return (
    <Tile className="module-surface analysis-panel">
      <div className="analysis-header">
        <div>
          <div className="module-title">{t('analysis.title', 'Setup quality')}</div>
          <div className="analysis-subtitle">
            {summaryText}
          </div>
        </div>
        <div className="analysis-actions">
          <button type="button" onClick={analysisResource.reload} disabled={gameMode || analysisState.loading || analysisState.refreshing}>
            {analysisState.refreshing ? t('common.refreshing', 'Refreshing') : t('common.refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {gameMode ? <div className="settings-message">{t('analysis.pausedGame', 'System analysis paused during game mode')}</div> : null}
      {hiddenWindow ? <div className="settings-message">{t('analysis.pausedHidden', 'System analysis paused while the window is hidden')}</div> : null}
      {analysisState.error ? <div className="action-error">{translatedNotice(analysisState.error, t)}</div> : null}

      <div className="analysis-grid">
        <div
          className={`analysis-score${analysis?.available ? '' : ' paused'}`}
          style={{ '--score-angle': `${Math.max(0, Math.min(100, score)) * 3.6}deg` }}
        >
          <div className="analysis-score-label">{t('analysis.score', 'Setup score')}</div>
          <div className="analysis-score-meter" aria-label={`${t('analysis.score', 'Setup score')} ${analysis?.available ? score : t('analysis.paused', 'paused')}`}>
            <div>
              <span className="analysis-score-value">{analysis?.available ? score : '--'}</span>
              <span className="analysis-score-unit">{analysis?.available ? '/100' : t('analysis.paused', 'PAUSED')}</span>
            </div>
          </div>
          <div className="analysis-score-detail">
            {analysis?.available
              ? t('analysis.gradeLine', '{{grade}} grade').replace('{{grade}}', gradeText)
              : gameMode
                ? t('analysis.noGameAnalysis', 'Setup quality pauses while a game is active')
                : hiddenWindow
                  ? t('analysis.noHiddenAnalysis', 'Setup quality pauses while the window is hidden')
                  : analysisState.loading
                    ? t('analysis.loading', 'Loading setup quality')
                    : t('analysis.unavailable', 'Setup quality is temporarily unavailable')}
          </div>
        </div>

        <div className="analysis-summary">
          <div>
            <span>{t('analysis.checksPassing', 'Ready checks')}</span>
            <strong>{analysis?.available ? `${goodChecks}/${checks.length}` : '0/0'}</strong>
          </div>
          <div>
            <span>{t('analysis.warnings', 'Needs review')}</span>
            <strong>{analysis?.available ? warningChecks : 0}</strong>
          </div>
          <div className="wide">
            <span>{t('analysis.categories', 'Setup areas')}</span>
            <strong>{analysis?.available ? categories.map((category) => categoryLabel(category, t)).join(' / ') : t('analysis.paused', 'Paused')}</strong>
          </div>
        </div>
      </div>

      {analysis?.available ? (
        <div className="analysis-check-list" aria-label={t('analysis.checkList', 'Setup checks')}>
          {checks.map((check) => (
            <div key={check.id} className={`analysis-check ${check.status}`}>
              <div className="analysis-check-top">
                <span>{checkLabel(check, t)}</span>
                <Tag type={checkTone(check.status)}>{statusLabel(check.status, t)}</Tag>
              </div>
              <div className="analysis-check-detail">{checkDetail(check, t)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="module-empty">
          {gameMode || hiddenWindow
            ? t('analysis.paused', 'Paused')
            : analysisState.loading
              ? t('analysis.loading', 'Loading setup quality')
              : t('analysis.unavailable', 'Setup quality is temporarily unavailable')}
        </div>
      )}
    </Tile>
  );
}

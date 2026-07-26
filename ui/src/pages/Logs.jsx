import { memo, useEffect, useMemo, useState } from 'react';
import { Tag, Tile } from '@carbon/react';
import { KpiCell } from '../components/KpiCell.jsx';
import { PageHeading } from '../components/PageHeading.jsx';
import { StatusTag } from '../components/StatusTag.jsx';
import { useBackendResource } from '../hooks/useBackendResource.js';
import { useI18n } from '../i18n.jsx';
import { translatedNotice } from '../utils/config.mjs';

const LOG_LIMIT = 500;
const REFRESH_INTERVAL_MS = 5000;
const SEVERITY_FILTERS = [
  { id: 'all', labelKey: 'process.filter.all', label: 'All' },
  { id: 'info', label: 'INFO' },
  { id: 'warning', label: 'WARN' },
  { id: 'error', label: 'ERROR' }
];

function formatLogTime(value) {
  if (!value) {
    return '-';
  }
  return value;
}

function severityTagType(severity) {
  if (severity === 'error') {
    return 'red';
  }
  if (severity === 'warning') {
    return 'yellow';
  }
  return 'gray';
}

function reasonText(payload, t) {
  if (!payload) {
    return t('logs.reason.loading', 'Loading logs');
  }
  if (payload.available) {
    return t('logs.reason.available', 'Showing latest {{count}} of {{limit}} lines', {
      count: payload.entries?.length ?? 0,
      limit: payload.limit ?? LOG_LIMIT
    });
  }
  if (payload.reason === 'log_file_not_configured') {
    return t('logs.reason.notConfigured', 'Set log_file in Settings to enable file logs');
  }
  if (payload.reason === 'log_file_missing') {
    return t('logs.reason.missing', 'Configured log file was not found');
  }
  return t('logs.reason.unavailable', 'Logs unavailable');
}

export const LogsPage = memo(function LogsPage({ live, page }) {
  const { t } = useI18n();
  const status = live.snapshot?.status || {};
  const gameMode = Boolean(status.game_mode);
  const enabled = !gameMode && live.visible;
  const [lastLoaded, setLastLoaded] = useState(null);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [query, setQuery] = useState('');
  const logsResource = useBackendResource(`/api/logs?limit=${LOG_LIMIT}`, { enabled });
  const payload = logsResource.data;

  useEffect(() => {
    if (payload) {
      setLastLoaded(new Date());
    }
  }, [payload]);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      logsResource.reload();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, logsResource.reload]);

  const entries = Array.isArray(payload?.entries) ? payload.entries : [];
  const categories = useMemo(() => {
    const unique = new Set();
    for (const entry of entries) {
      if (entry.category) {
        unique.add(entry.category);
      }
    }
    return Array.from(unique).sort();
  }, [entries]);

  const filteredEntries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (severityFilter !== 'all' && entry.severity !== severityFilter) {
        return false;
      }
      if (categoryFilter !== 'all' && entry.category !== categoryFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return [
        entry.timestamp,
        entry.severity,
        entry.category,
        entry.tag,
        entry.message,
        entry.raw,
        String(entry.line)
      ].some((value) => String(value || '').toLowerCase().includes(needle));
    });
  }, [entries, severityFilter, categoryFilter, query]);

  const counts = useMemo(() => entries.reduce(
    (acc, entry) => {
      acc.total += 1;
      if (entry.severity === 'warning') {
        acc.warning += 1;
      } else if (entry.severity === 'error') {
        acc.error += 1;
      }
      return acc;
    },
    { total: 0, warning: 0, error: 0 }
  ), [entries]);

  return (
    <section className="page logs-page" aria-labelledby="logs-title">
      <PageHeading page={page} titleId="logs-title">
        <StatusTag status={status} />
        <Tag type={gameMode ? 'yellow' : payload?.available ? 'green' : 'gray'}>
          {gameMode ? t('logs.pausedTag', 'Paused in game mode') : payload?.available ? t('logs.fileLog', 'File log') : t('logs.noLogFile', 'No log file')}
        </Tag>
      </PageHeading>

      <div className="settings-toolbar logs-toolbar">
        <div className="settings-path">{payload?.path || t('logs.pathFallback', 'log_file not configured')}</div>
        <div className="settings-actions">
          <button type="button" onClick={logsResource.reload} disabled={gameMode || logsResource.loading || logsResource.refreshing}>
            {logsResource.refreshing ? t('common.refreshing', 'Refreshing') : t('common.refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {gameMode ? <div className="settings-message">{t('logs.pausedMessage', 'Log refresh paused during game mode')}</div> : null}
      {logsResource.error ? <div className="action-error">{translatedNotice(logsResource.error, t)}</div> : null}

      <div className="kpi-strip logs-summary-grid" aria-label="Log summary">
        <KpiCell label={t('logs.loadedLines', 'Loaded Lines')} value={counts.total} detail={reasonText(payload, t)} highlight />
        <KpiCell label={t('analysis.warnings', 'Warnings')} value={counts.warning} detail={t('logs.warningsDetail', 'WARN severity entries')} tone={counts.warning ? 'warning' : 'default'} />
        <KpiCell label={t('readiness.errors', 'Errors')} value={counts.error} detail={t('logs.errorsDetail', 'ERROR severity entries')} tone={counts.error ? 'warning' : 'default'} />
        <KpiCell label={t('logs.lastRefresh', 'Last Refresh')} value={lastLoaded ? lastLoaded.toLocaleTimeString() : '-'} detail={t('logs.refreshDetail', 'Only while this page is open')} />
      </div>

      <Tile className="module-surface logs-module">
        <div className="logs-module-header">
          <div>
            <div className="module-title">{t('logs.viewer', 'Log Viewer')}</div>
            <div className="logs-subtitle">{reasonText(payload, t)}</div>
          </div>
          <div className="process-count-readout">{filteredEntries.length} {t('common.shown', 'shown')}</div>
        </div>

        <div className="logs-filter-bar">
          <div className="process-filter-group" aria-label="Severity filters">
            {SEVERITY_FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                className={severityFilter === filter.id ? 'active' : ''}
                onClick={() => setSeverityFilter(filter.id)}
              >
                {filter.labelKey ? t(filter.labelKey, filter.label) : filter.label}
              </button>
            ))}
          </div>
          <select
            className="log-category-select"
            value={categoryFilter}
            aria-label="Log category"
            onChange={(event) => setCategoryFilter(event.target.value)}
          >
            <option value="all">{t('logs.allCategories', 'All categories')}</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
          <input
            className="process-search"
            type="search"
            value={query}
            placeholder={t('logs.search', 'Search logs')}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="log-table-wrap">
          <table className="log-table">
            <thead>
              <tr>
                <th>{t('logs.column.line', 'Line')}</th>
                <th>{t('logs.column.time', 'Time')}</th>
                <th>{t('logs.column.severity', 'Severity')}</th>
                <th>{t('logs.column.category', 'Category')}</th>
                <th>{t('logs.column.message', 'Message')}</th>
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((entry) => (
                <tr key={`${entry.line}-${entry.raw}`} className={`log-row ${entry.severity || 'info'}`}>
                  <td className="mono">{entry.line}</td>
                  <td className="mono">{formatLogTime(entry.timestamp)}</td>
                  <td>
                    <Tag type={severityTagType(entry.severity)}>{entry.tag || entry.severity || 'INFO'}</Tag>
                  </td>
                  <td className="mono">{entry.category || 'general'}</td>
                  <td className="log-message" title={entry.raw}>{entry.message || entry.raw}</td>
                </tr>
              ))}
              {!filteredEntries.length ? (
                <tr>
                  <td className="process-empty" colSpan={5}>
                    {logsResource.loading ? t('logs.loading', 'Loading logs') : t('logs.empty', 'No log entries match filters')}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Tile>
    </section>
  );
});

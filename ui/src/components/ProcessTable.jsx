import { memo, useDeferredValue, useMemo, useState } from 'react';
import { Tile } from '@carbon/react';
import { PRIORITY_CLASS_LABELS, PROCESS_FILTERS } from '../constants/processes.mjs';
import { useI18n } from '../i18n.jsx';
import { formatCpuSets, formatPriorityClass } from '../utils/format.mjs';
import { ProcessStatusBadge } from './ProcessStatusBadge.jsx';

function processMatchesFilter(process, filter) {
  if (filter === 'all') {
    return true;
  }
  if (filter === 'game') {
    return Boolean(process.game)
      || process.status === 'game'
      || process.source === 'observed_game'
      || Boolean(process.tuning_state);
  }
  if (filter === 'protected') {
    return Boolean(process.protected) || process.status === 'protected';
  }
  return process.status === filter;
}

function processMatchesQuery(process, query) {
  if (!query) {
    return true;
  }
  const haystack = `${process.pid || ''} ${process.name || ''} ${process.source || ''} ${process.status || ''}`.toLowerCase();
  return haystack.includes(query);
}

function formatPriorityLabel(priorityClass, t) {
  if (typeof priorityClass !== 'number') {
    return t('priority.default', formatPriorityClass(priorityClass));
  }
  return t(
    `priority.${priorityClass}`,
    PRIORITY_CLASS_LABELS[priorityClass] || t('priority.class', 'Class {{value}}', { value: priorityClass })
  );
}

function formatCpuSetsLabel(process, t) {
  const value = formatCpuSets(process.cpu_set_ids, process.affinity_mask);
  return value === 'None' ? t('common.none', 'None') : value;
}

function formatProcessMode(mode, t) {
  return mode ? t(`process.mode.${mode}`, mode) : t('process.modeWaiting', 'Waiting for optimization activity');
}

function processReason(process, t) {
  const status = process.status || (process.game ? 'game' : 'tracked');
  if (process.tuning_state) {
    return t(
      `process.reason.game.${process.tuning_state}`,
      t('process.reason.game', 'The game is detected and prepared for stable frame delivery'),
      { game: process.name || t('process.nameFallback', 'game') }
    );
  }
  const key = status === 'jailed'
    ? 'limited'
    : status === 'foreground'
      ? 'foreground'
      : status;
  return t(`process.reason.${key}`, process.source || t('process.reason.tracked', 'Observed while monitoring your game session'));
}

function processActionStatus(process) {
  if (process.game || process.status === 'game' || process.source === 'observed_game' || process.tuning_state) {
    return 'game';
  }
  return process.status || 'tracked';
}

/** @param {{snapshot: ?{processes?: import('../types.js').ProcessRow[], process_mode?: string}}} props */
export const ProcessTable = memo(function ProcessTable({ snapshot }) {
  const { t } = useI18n();
  const [processFilter, setProcessFilter] = useState('all');
  const [processQuery, setProcessQuery] = useState('');
  const deferredQuery = useDeferredValue(processQuery);
  const processes = Array.isArray(snapshot?.processes) ? snapshot.processes : [];
  const normalizedQuery = deferredQuery.trim().toLowerCase();

  const filteredProcesses = useMemo(() => {
    const list = Array.isArray(snapshot?.processes) ? snapshot.processes : [];
    const rows = [];
    for (const process of list) {
      if (
        processMatchesFilter(process, processFilter)
        && processMatchesQuery(process, normalizedQuery)
      ) {
        rows.push(process);
      }
    }
    return rows;
  }, [snapshot?.processes, processFilter, normalizedQuery]);

  return (
    <Tile className="module-surface process-module">
      <div className="process-module-header">
        <div>
          <div className="module-title" id="process-table-title">{t('process.title', 'Optimization activity')}</div>
          <div className="process-mode-note">
            {formatProcessMode(snapshot?.process_mode, t)}
          </div>
        </div>
        <div className="process-count-readout">
          {filteredProcesses.length} / {processes.length}
        </div>
      </div>

      <div className="process-filter-bar" aria-label={t('process.filters', 'Activity filters')}>
        <div className="process-filter-group" role="group" aria-label={t('process.statusFilter', 'Action filter')}>
          {PROCESS_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              className={processFilter === filter.id ? 'active' : ''}
              aria-pressed={processFilter === filter.id}
              onClick={() => setProcessFilter(filter.id)}
            >
              {t(`process.filter.${filter.id}`, filter.label)}
            </button>
          ))}
        </div>
        <input
          aria-label={t('process.searchLabel', 'Search optimization activity')}
          className="process-search"
          type="search"
          placeholder={t('process.search', 'Search PID or application')}
          value={processQuery}
          onChange={(event) => setProcessQuery(event.target.value)}
        />
      </div>

      <div className="process-table-wrap">
        <table className="process-table" aria-labelledby="process-table-title">
          <thead>
            <tr>
              <th scope="col">{t('process.column.action', 'Action')}</th>
              <th scope="col">{t('process.column.name', 'Application')}</th>
              <th scope="col">{t('process.column.pid', 'PID')}</th>
              <th scope="col">{t('process.column.priority', 'Priority')}</th>
              <th scope="col">{t('process.column.cpuPlacement', 'CPU allocation')}</th>
              <th scope="col">{t('process.column.reason', 'Why it matters')}</th>
            </tr>
          </thead>
          <tbody>
            {filteredProcesses.length ? (
              filteredProcesses.map((process) => (
                <tr key={`${process.pid}-${process.create_time || 0}`} className={`process-row ${processActionStatus(process)}`}>
                  <td><ProcessStatusBadge status={processActionStatus(process)} /></td>
                  <td className="process-name" title={process.name || ''}>{process.name || t('process.nameFallback', 'process')}</td>
                  <td className="mono">{process.pid}</td>
                  <td>{formatPriorityLabel(process.priority_class, t)}</td>
                  <td className="mono" title={formatCpuSetsLabel(process, t)}>
                    {formatCpuSetsLabel(process, t)}
                  </td>
                  <td>{processReason(process, t)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="process-empty" colSpan={6}>{t('process.empty', 'No optimization activity matches this view')}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Tile>
  );
});

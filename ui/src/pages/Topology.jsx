import { memo, useEffect, useMemo, useState } from 'react';
import { Tag, Tile } from '@carbon/react';
import { KpiCell } from '../components/KpiCell.jsx';
import { PageHeading } from '../components/PageHeading.jsx';
import { StatusTag } from '../components/StatusTag.jsx';
import { PARTITION_LABELS } from '../constants/topology.mjs';
import { useBackendResource } from '../hooks/useBackendResource.js';
import { translatedNotice } from '../utils/config.mjs';
import { formatCacheSize, formatCoreLabel, formatCpuSets } from '../utils/format.mjs';
import { groupCoresByLlc } from '../utils/topology.js';
import { useI18n } from '../i18n.jsx';

const PARTITION_FALLBACK_LABELS = {
  game: 'Game',
  background: 'Background',
  housekeeping: 'Housekeeping',
  unassigned: 'Unassigned'
};

const CORE_TYPE_FALLBACK_LABELS = {
  performance: 'P-core',
  efficiency: 'E-core',
  standard: 'Core',
  mixed: 'Mixed'
};

export const TopologyPage = memo(function TopologyPage({ live, page }) {
  const { t } = useI18n();
  const status = live.snapshot?.status || {};
  const [selectedCoreId, setSelectedCoreId] = useState(null);
  // The initial load also refreshes: the CPU map must reflect the current
  // partitioning, not a cached snapshot.
  const topologyResource = useBackendResource('/api/topology?refresh=1');
  const topology = topologyResource.data;

  useEffect(() => {
    if (topology) {
      setSelectedCoreId((current) => current || topology.cores?.[0]?.id || null);
    }
  }, [topology]);

  const cores = Array.isArray(topology?.cores) ? topology.cores : [];
  const llcGroups = useMemo(
    () => groupCoresByLlc(cores, Array.isArray(topology?.llc_groups) ? topology.llc_groups : []),
    [cores, topology?.llc_groups]
  );
  const selectedCore = useMemo(
    () => cores.find((core) => core.id === selectedCoreId) || cores[0] || null,
    [cores, selectedCoreId]
  );
  const partitions = topology?.partitions || {};
  const summary = topology?.summary || {};
  const partitionLabel = (partition) => t(`topology.partition.${partition}`, PARTITION_FALLBACK_LABELS[partition] || PARTITION_LABELS[partition] || partition);
  const coreTypeLabel = (core) => {
    const typeKey = core?.efficiency_type || 'standard';
    const type = t(`topology.coreType.${typeKey}`, CORE_TYPE_FALLBACK_LABELS[typeKey] || formatCoreLabel(core).replace(' / Parked', ''));
    return core?.parked ? `${type} / ${t('topology.parked', 'Parked')}` : type;
  };

  return (
    <section className="page topology-page" aria-labelledby="topology-title">
      <PageHeading page={page} titleId="topology-title">
        <StatusTag status={status} />
        <Tag type={topology?.available ? 'green' : 'gray'}>
          {topology?.available ? t('topology.available', 'Topology available') : t('topology.unavailable', 'Topology unavailable')}
        </Tag>
      </PageHeading>

      <div className="settings-toolbar topology-toolbar">
        <div className="settings-path">
          {topology?.refresh?.blocked_reason
            ? t('topology.refreshBlocked', 'Refresh blocked: {{reason}}', { reason: topology.refresh.blocked_reason })
            : t('topology.readOnly', 'Read-only CPU map')}
        </div>
        <div className="settings-actions">
          <button type="button" onClick={topologyResource.reload} disabled={topologyResource.loading || topologyResource.refreshing}>
            {topologyResource.refreshing ? t('common.refreshing', 'Refreshing') : t('common.refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {topologyResource.error ? <div className="action-error">{translatedNotice(topologyResource.error, t)}</div> : null}

      <div className="kpi-strip topology-summary-grid" aria-label="Topology summary">
        <KpiCell label={t('topology.totalCores', 'Total Cores')} value={summary.core_count ?? cores.length} detail={t('topology.logicalProcessors', '{{count}} logical processors', { count: summary.logical_processor_count ?? 0 })} highlight />
        <KpiCell label={partitionLabel('game')} value={partitions.game?.core_count ?? 0} detail={t('topology.cpuSetsCount', '{{count}} CPU assignments', { count: partitions.game?.logical_processor_count ?? 0 })} tone="positive" />
        <KpiCell label={partitionLabel('background')} value={partitions.background?.core_count ?? 0} detail={t('topology.cpuSetsCount', '{{count}} CPU assignments', { count: partitions.background?.logical_processor_count ?? 0 })} />
        <KpiCell label={partitionLabel('housekeeping')} value={partitions.housekeeping?.core_count ?? 0} detail={t('topology.cpuSetsCount', '{{count}} CPU assignments', { count: partitions.housekeeping?.logical_processor_count ?? 0 })} />
      </div>

      <div className="topology-layout">
        <Tile className="module-surface topology-map">
          <div className="topology-map-header">
            <div>
              <div className="module-title">{t('topology.map', 'CPU Map')}</div>
              <div className="topology-subtitle">
                {summary.heterogeneous_efficiency ? t('topology.hybridLayout', 'Hybrid P-core / E-core layout') : t('topology.homogeneousLayout', 'Homogeneous core layout')}
              </div>
            </div>
            <div className="topology-legend" aria-label="Partition legend">
              <span className="legend-item partition-game">{partitionLabel('game')}</span>
              <span className="legend-item partition-background">{partitionLabel('background')}</span>
              <span className="legend-item partition-housekeeping">{partitionLabel('housekeeping')}</span>
              <span className="legend-item partition-unassigned">{partitionLabel('unassigned')}</span>
            </div>
          </div>

          {topologyResource.loading ? (
            <div className="module-empty">{t('topology.loading', 'Loading topology')}</div>
          ) : cores.length ? (
            <div className="llc-group-list">
              {llcGroups.map((llc) => (
                <section className="llc-group" key={llc.id} aria-label={`LLC ${llc.llc_index}`}>
                  <div className="llc-group-header">
                    <span>LLC {llc.llc_index}</span>
                    <span>{t('topology.group', 'Group')} {llc.group}</span>
                    <span>{formatCacheSize(llc.l3_size_bytes)}</span>
                    <span>{t('topology.coresCount', '{{count}} cores', { count: llc.cores.length })}</span>
                  </div>
                  <div className="core-grid">
                    {llc.cores.map((core) => {
                      const partition = core.partition || 'unassigned';
                      const translatedPartition = partitionLabel(partition);
                      const selected = selectedCore?.id === core.id;
                      return (
                        <button
                          key={core.id}
                          type="button"
                          className={`core-tile partition-${partition} ${core.efficiency_type || 'standard'}${core.parked ? ' parked' : ''}${selected ? ' selected' : ''}`}
                          title={`${t('topology.core', 'Core')} ${core.core_index} / ${coreTypeLabel(core)} / ${translatedPartition}`}
                          aria-pressed={selected}
                          onClick={() => setSelectedCoreId(core.id)}
                        >
                          <span className="core-index">C{core.core_index}</span>
                          <span className="core-type">{coreTypeLabel(core)}</span>
                          <span className="core-partition">{translatedPartition}</span>
                          <span className="core-logicals">{t('topology.logicalProcessorsShort', '{{count}} LP', { count: core.logical_processor_count })}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="module-empty">{t('topology.noData', 'No topology data')}</div>
          )}
        </Tile>

        <Tile className="module-surface core-detail-panel">
          <div className="module-title">{t('topology.coreDetails', 'Core Details')}</div>
          {selectedCore ? (
            <div className="core-detail-grid">
              <div>
                <span>{t('topology.core', 'Core')}</span>
                <strong>C{selectedCore.core_index}</strong>
              </div>
              <div>
                <span>{t('topology.type', 'Type')}</span>
                <strong>{coreTypeLabel(selectedCore)}</strong>
              </div>
              <div>
                <span>{t('topology.partition', 'Partition')}</span>
                <strong>{partitionLabel(selectedCore.partition)}</strong>
              </div>
              <div>
                <span>{t('topology.group', 'Group')}</span>
                <strong>{selectedCore.group}</strong>
              </div>
              <div>
                <span>LLC</span>
                <strong>{selectedCore.llc_index}</strong>
              </div>
              <div>
                <span>L3</span>
                <strong>{formatCacheSize(selectedCore.l3_size_bytes)}</strong>
              </div>
              <div>
                <span>{t('topology.efficiency', 'Efficiency')}</span>
                <strong>{selectedCore.efficiency_class}</strong>
              </div>
              <div>
                <span>{t('topology.status', 'Status')}</span>
                <strong>{selectedCore.parked ? t('topology.parked', 'Parked') : t('dashboard.active', 'Active')}</strong>
              </div>
              <div className="wide">
                <span>{t('topology.cpuSets', 'CPU assignments')}</span>
                <strong>{formatCpuSets(selectedCore.cpu_set_ids)}</strong>
              </div>
              <div className="wide">
                <span>{t('topology.logicalProcessorsLabel', 'Logical Processors')}</span>
                <strong>{(selectedCore.logical_indices || []).join(', ') || t('common.none', 'None')}</strong>
              </div>
            </div>
          ) : (
            <div className="module-empty">{t('topology.selectCore', 'Select a core')}</div>
          )}
        </Tile>
      </div>
    </section>
  );
});

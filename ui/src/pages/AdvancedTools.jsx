import { memo, useMemo } from 'react';
import { Tag, Tile } from '@carbon/react';
import { KpiCell } from '../components/KpiCell.jsx';
import { PageHeading } from '../components/PageHeading.jsx';
import { StatusTag } from '../components/StatusTag.jsx';
import { useBackendResource } from '../hooks/useBackendResource.js';
import { useI18n } from '../i18n.jsx';
import { translatedNotice } from '../utils/config.mjs';

function msiLabel(value, t) {
  if (value === true) {
    return t('common.enabled', 'Enabled');
  }
  if (value === false) {
    return t('common.disabled', 'Disabled');
  }
  return t('advanced.noMsiFlag', 'No MSI flag');
}

function msiTagType(value) {
  if (value === true) {
    return 'green';
  }
  if (value === false) {
    return 'yellow';
  }
  return 'gray';
}

function deviceClassLabel(deviceClass, t) {
  return deviceClass === 'PCI device'
    ? t('advanced.pciDevice', 'PCI device')
    : deviceClass;
}

export const AdvancedToolsPage = memo(function AdvancedToolsPage({ live }) {
  const { t } = useI18n();
  const status = live.snapshot?.status || {};
  const gameMode = Boolean(status.game_mode);
  const toolsResource = useBackendResource('/api/msi', {
    enabled: !gameMode && live.visible,
    refreshPath: '/api/msi?refresh=1'
  });
  const payload = toolsResource.data;

  const devices = Array.isArray(payload?.devices) ? payload.devices : [];
  const summary = payload?.summary || { total: 0, enabled: 0, disabled: 0, unknown: 0 };
  const byClass = useMemo(() => {
    const counts = new Map();
    for (const device of devices) {
      const label = deviceClassLabel(device.device_class, t);
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    return Array.from(counts.entries()).map(([deviceClass, count]) => `${deviceClass}: ${count}`).join(' / ') || t('advanced.noDevices', 'No devices loaded');
  }, [devices, t]);

  return (
    <section className="page advanced-tools-page" aria-labelledby="advanced-tools-title">
      <PageHeading title="Advanced Tools" titleKey="nav.advanced" titleId="advanced-tools-title">
        <StatusTag status={status} />
        <Tag type={gameMode ? 'yellow' : payload?.available ? 'green' : 'gray'}>
          {gameMode ? t('advanced.paused', 'Paused in game mode') : t('advanced.readOnly', 'Read-only')}
        </Tag>
      </PageHeading>

      <div className="settings-toolbar">
        <div className="settings-path">{t('advanced.registryPath', 'HKLM\\SYSTEM\\CurrentControlSet\\Enum\\PCI')}</div>
        <div className="settings-actions">
          <button type="button" onClick={toolsResource.reload} disabled={gameMode || toolsResource.loading || toolsResource.refreshing}>
            {toolsResource.refreshing ? t('common.refreshing', 'Refreshing') : t('common.refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {gameMode ? <div className="settings-message">{t('advanced.pausedMessage', 'MSI registry inspection paused during game mode')}</div> : null}
      {toolsResource.error ? <div className="action-error">{translatedNotice(toolsResource.error, t)}</div> : null}

      <div className="kpi-strip logs-summary-grid" aria-label="MSI summary">
        <KpiCell label={t('advanced.devices', 'Devices')} value={summary.total} detail={byClass} highlight />
        <KpiCell label={t('advanced.msiEnabled', 'MSI Enabled')} value={summary.enabled} detail={t('advanced.enabledDetail', 'Message Signaled Interrupts enabled')} />
        <KpiCell label={t('advanced.msiDisabled', 'MSI Disabled')} value={summary.disabled} detail={t('advanced.disabledDetail', 'Could be reviewed manually')} tone={summary.disabled ? 'warning' : 'default'} />
        <KpiCell label={t('advanced.noMsiFlag', 'No MSI flag')} value={summary.unknown} detail={t('advanced.noMsiFlagDetail', 'Registry value not declared')} />
      </div>

      <Tile className="module-surface msi-module">
        <div className="logs-module-header">
          <div>
            <div className="module-title">{t('advanced.title', 'Message Signaled Interrupts')}</div>
            <div className="logs-subtitle">{t('advanced.subtitle', 'Read-only PCI device viewer. Changes usually require restart and are intentionally not applied here.')}</div>
          </div>
          <div className="process-count-readout">{payload?.readonly ? t('common.readonly', 'readonly') : t('common.unavailable', 'unavailable')}</div>
        </div>

        <div className="log-table-wrap">
          <table className="msi-table">
            <thead>
              <tr>
                <th>{t('advanced.device', 'Device')}</th>
                <th>{t('advanced.class', 'Class')}</th>
                <th>MSI</th>
                <th>{t('advanced.limit', 'Limit')}</th>
                <th>{t('advanced.instance', 'Instance')}</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.instance_id}>
                  <td>{device.name}</td>
                  <td className="mono">{deviceClassLabel(device.device_class, t)}</td>
                  <td><Tag type={msiTagType(device.msi_enabled)}>{msiLabel(device.msi_enabled, t)}</Tag></td>
                  <td className="mono">{device.message_limit ?? '-'}</td>
                  <td className="mono msi-instance" title={device.instance_id}>{device.instance_id}</td>
                </tr>
              ))}
              {!devices.length ? (
                <tr>
                  <td className="process-empty" colSpan={5}>
                    {toolsResource.loading ? t('advanced.loadingDevices', 'Loading MSI devices') : payload?.reason || t('advanced.noDevicesFound', 'No PCI MSI devices found')}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="settings-message msi-warning">{t('advanced.restartWarning', 'Restart required after manual MSI registry changes. This viewer does not write registry values.')}</div>
      </Tile>
    </section>
  );
});

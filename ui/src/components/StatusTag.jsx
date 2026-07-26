import { Tag } from '@carbon/react';
import { isMonitoringActive } from '../utils/status.mjs';
import { useI18n } from '../i18n.jsx';

export function StatusTag({ status }) {
  const { t } = useI18n();
  const monitoring = isMonitoringActive(status);
  const type = status?.game_mode ? 'cyan' : monitoring ? 'green' : 'gray';
  const label = status?.game_mode
    ? t('status.gameMode', 'Optimizing game')
    : monitoring
      ? t('status.engineRunning', 'Monitoring active')
      : t('status.engineIdle', 'Monitoring paused');
  return <Tag type={type}>{label}</Tag>;
}

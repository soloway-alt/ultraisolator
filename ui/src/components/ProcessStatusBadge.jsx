import { PROCESS_STATUS_LABELS } from '../constants/processes.mjs';
import { useI18n } from '../i18n.jsx';

export function ProcessStatusBadge({ status }) {
  const { t } = useI18n();
  const marker = status || 'tracked';
  const label = t(`process.status.${marker}`, PROCESS_STATUS_LABELS[marker] || marker);
  return (
    <span className={`status-badge ${marker}`}>
      <span className="status-badge-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

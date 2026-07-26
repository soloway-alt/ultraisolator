// Compat rule for the engine's monitoring flag: `monitoring_active` is the
// newer status field; older snapshots only carry the legacy `running` flag,
// so fall back to it when `monitoring_active` is absent.
export function isMonitoringActive(status) {
  return status?.monitoring_active === undefined
    ? Boolean(status?.running)
    : Boolean(status?.monitoring_active);
}

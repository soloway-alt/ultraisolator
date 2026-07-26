import { memo, useState } from 'react';
import { Tag } from '@carbon/react';
import PlayIcon from '@carbon/icons-react/es/PlayFilledAlt.js';
import StopIcon from '@carbon/icons-react/es/StopFilledAlt.js';
import RestoreIcon from '@carbon/icons-react/es/Renew.js';
import { KpiCell } from '../components/KpiCell.jsx';
import { PageHeading } from '../components/PageHeading.jsx';
import { ProcessTable } from '../components/ProcessTable.jsx';
import { ReadinessChecklist } from '../components/ReadinessChecklist.jsx';
import { StatusTag } from '../components/StatusTag.jsx';
import { SystemAnalysis } from '../components/SystemAnalysis.jsx';
import { formatPartitions, formatTimerResolution } from '../utils/format.mjs';
import { isMonitoringActive } from '../utils/status.mjs';
import { postLifecycleAction } from '../utils/lifecycle.js';
import { useI18n } from '../i18n.jsx';

function formatProcessMode(mode, t) {
  return mode ? t(`process.mode.${mode}`, mode) : t('dashboard.waitingSnapshot', 'Waiting for activity');
}

function formatAntiCheatMode(mode, t) {
  return mode ? t(`antiCheat.${mode}`, mode) : t('common.na', 'N/A');
}

function capabilityIssueText(issue, t) {
  if (typeof issue === 'string') {
    return t(`capability.${issue}`, issue);
  }
  const code = issue?.code || issue?.key || 'unknown';
  return t(
    issue?.message_key || `capability.${code}`,
    issue?.message || issue?.detail || code,
    issue?.data || {}
  );
}

export const DashboardPage = memo(function DashboardPage({ live, page }) {
  const { t } = useI18n();
  const [actionState, setActionState] = useState({ pending: null, error: null, lastAction: null });
  const snapshot = live.snapshot;
  const status = snapshot?.status || {};
  const processCount = snapshot?.process_count ?? status.tracked_process_count ?? 0;
  const hasSnapshot = Boolean(snapshot);
  const activeGamePids = Array.isArray(status.active_game_pids) ? status.active_game_pids : [];
  const activeGames = Array.isArray(status.active_games) ? status.active_games : [];
  const capabilityIssues = Array.isArray(status.capability_issues) ? status.capability_issues : [];
  const actionableCapabilityIssues = capabilityIssues.filter((issue) => (
    typeof issue === 'string' || !issue?.severity || issue.severity === 'warning' || issue.severity === 'error'
  ));
  const capabilityMessages = capabilityIssues.length
    ? actionableCapabilityIssues.map((issue) => capabilityIssueText(issue, t))
    : (Array.isArray(status.capability_notes) ? status.capability_notes : []);
  const isRunning = isMonitoringActive(status);
  const gameMode = Boolean(status.game_mode);
  const activeProcess = Array.isArray(snapshot?.processes)
    ? snapshot.processes.find((process) => process.game || process.status === 'game')
    : null;
  const activeGame = activeGames[0] || activeProcess;
  const gameDetected = Boolean(activeGame) || gameMode;
  const reportedFailureCount = Number(status.reported_failure_count || 0);
  const recoveryClean = hasSnapshot && !status.persistent_recovery_incomplete && reportedFailureCount === 0;
  const needsAttention = !status.admin || !recoveryClean || capabilityMessages.length > 0;
  const restored = actionState.lastAction === 'recover' && !actionState.error && !isRunning;
  const partitions = formatPartitions(status.cpu_partitions, {
    game: t('process.filter.game', 'Game'),
    background: t('process.filter.jailed', 'Background'),
    system: t('dashboard.systemProcesses', 'System')
  });
  const timerValue = status.timer_resolution_applied
    ? formatTimerResolution(status.timer_resolution_applied)
    : t('dashboard.notApplied', 'Not applied');
  const antiCheatMode = status.anti_cheat_mode ? formatAntiCheatMode(status.anti_cheat_mode, t) : (isRunning ? t('common.na', 'N/A') : t('dashboard.monitoringPaused', 'Monitoring paused'));
  const profileName = status.anti_cheat_mode
    ? t('dashboard.profileName', '{{mode}} protection', { mode: antiCheatMode })
    : t('dashboard.profilePending', 'Protection profile');
  const activeGameName = activeGame?.name || t('dashboard.noGame', 'No game detected');
  const activeGameTuningState = activeGame?.tuning_state || (gameMode ? 'applied' : 'pending');
  const statusConfig = status.config && typeof status.config === 'object' ? status.config : null;
  const powerPlanDisabled = statusConfig?.disable_power_scheme_switch === true;
  const timerTuningDisabled = statusConfig?.disable_timer_resolution_tweak === true;
  const dashboardState = !hasSnapshot
    ? 'connecting'
    : actionState.pending
      ? 'working'
      : restored
        ? 'restored'
        : gameDetected
          ? 'active'
          : isRunning
            ? 'detecting'
            : needsAttention
              ? 'attention'
              : 'ready';
  const dashboardStateLabel = dashboardState === 'active'
    ? activeGameTuningState === 'applied'
      ? t('dashboard.optimizingGame', 'Optimizing {{game}}', { game: activeGameName })
      : t('dashboard.gameDetected', 'Game detected')
    : dashboardState === 'connecting'
      ? t(`connection.${live.connectionState}`, live.connectionState)
      : dashboardState === 'detecting'
        ? t('dashboard.detecting', 'Monitoring for games')
        : dashboardState === 'restored'
          ? t('dashboard.restored', 'Restored')
          : dashboardState === 'ready'
            ? t('dashboard.ready', 'Ready')
            : dashboardState === 'working'
              ? t('dashboard.working', 'Applying changes')
              : t('dashboard.attention', 'Action required');
  const dashboardStateDetail = dashboardState === 'active'
      ? t(`dashboard.tuningState.${activeGameTuningState}`, activeGameName, { game: activeGameName })
    : dashboardState === 'connecting'
      ? t('dashboard.connectingDetail', 'Connecting to local monitoring')
      : dashboardState === 'detecting'
        ? t('dashboard.detectingDetail', 'UltraIsolator is watching for your configured games')
        : dashboardState === 'restored'
          ? t('dashboard.restoredDetail', 'Original system settings were restored')
          : dashboardState === 'ready'
            ? t('dashboard.readyDetail', 'Your configuration is ready')
            : dashboardState === 'working'
              ? t('dashboard.workingDetail', 'Waiting for local confirmation')
              : capabilityMessages[0] || (!status.admin
                ? t('dashboard.adminRequired', 'Administrator access is required for full tuning')
                : t('dashboard.recoveryReview', 'Review recovery status before starting'));
  const plannedChanges = [
    {
      id: 'background-isolation',
      label: t('dashboard.backgroundIsolation', 'Background control'),
      value: status.background_jailing
        ? t('common.enabled', 'Enabled')
        : t('common.disabled', 'Disabled'),
      state: status.background_jailing ? 'enabled' : 'disabled'
    },
    {
      id: 'anti-cheat-policy',
      label: t('dashboard.antiCheat', 'Anti-cheat'),
      value: antiCheatMode,
      state: 'configured'
    },
    {
      id: 'power-plan',
      label: t('dashboard.powerPlan', 'Power Plan'),
      value: status.power_plan_active
        ? t('dashboard.active', 'Active')
        : statusConfig
          ? powerPlanDisabled
            ? t('common.disabled', 'Disabled')
            : t('dashboard.onGameDetection', 'On game detection')
          : t('dashboard.automatic', 'Automatic'),
      state: status.power_plan_active ? 'active' : powerPlanDisabled ? 'disabled' : statusConfig ? 'planned' : 'configured'
    },
    {
      id: 'timer-tuning',
      label: t('dashboard.timer', 'Timer'),
      value: status.timer_resolution_applied
        ? timerValue
        : statusConfig
          ? timerTuningDisabled
            ? t('common.disabled', 'Disabled')
            : t('dashboard.onGameDetection', 'On game detection')
          : t('dashboard.automatic', 'Automatic'),
      state: status.timer_resolution_applied ? 'active' : timerTuningDisabled ? 'disabled' : statusConfig ? 'planned' : 'configured'
    }
  ];

  const runAction = async (action) => {
    setActionState({ pending: action, error: null, lastAction: null });
    try {
      await postLifecycleAction(action);
      setActionState({ pending: null, error: null, lastAction: action });
    } catch (error) {
      setActionState({
        pending: null,
        error: error instanceof Error ? error.message : t('dashboard.actionFailed', '{{action}} failed', { action }),
        lastAction: action
      });
    }
  };

  return (
    <section className="page dashboard-page" aria-labelledby="dashboard-title">
      <PageHeading page={page} titleId="dashboard-title">
        <StatusTag status={status} />
        <Tag type={live.connectionState === 'connected' ? 'green' : 'gray'}>
          {t(`connection.${live.connectionState}`, live.connectionState)}
        </Tag>
      </PageHeading>

      <div className={`dashboard-profile-hero dashboard-status-panel dashboard-state-${dashboardState}${gameMode ? ' game-mode' : ''}`}>
        <div className="dashboard-profile-main mode-readout">
          <div className="dashboard-profile-eyebrow kpi-label">{t('dashboard.sessionProfile', 'Session profile')}</div>
          <div className="dashboard-profile-name mode-value">{profileName}</div>
          <div className="dashboard-profile-game">
            <span>{t('dashboard.activeGame', 'Active game')}</span>
            <strong>{activeGameName}</strong>
          </div>
          <div className="dashboard-profile-detail mode-detail">
            {activeGamePids.length ? `${t('dashboard.activePids', 'Active PIDs')} ${activeGamePids.join(', ')}` : t('dashboard.waitingForGame', 'Waiting for a configured game')}
          </div>
          <div className={`dashboard-profile-state is-${dashboardState}`} role="status" aria-live="polite">
            <span className="dashboard-profile-state-indicator" aria-hidden="true" />
            <span>
              <strong>{dashboardStateLabel}</strong>
              <small>{dashboardStateDetail}</small>
            </span>
          </div>
        </div>

        <section className="planned-change-summary capability-grid" aria-label={t('dashboard.sessionPlan', 'Session plan')}>
          {plannedChanges.map((change) => (
            <div className={`planned-change-item is-${change.state}`} key={change.id}>
              <span>{change.label}</span>
              <strong>{change.value}</strong>
            </div>
          ))}
        </section>

        <div className="dashboard-profile-actions quick-actions" aria-label={t('dashboard.quickActions', 'Quick actions')}>
          <button className="dashboard-primary-action" type="button" onClick={() => runAction('start')} disabled={Boolean(actionState.pending) || isRunning}>
            <PlayIcon size={16} />
            {t('dashboard.resumeMonitoring', 'Resume monitoring')}
          </button>
          <button className="dashboard-secondary-action" type="button" onClick={() => runAction('stop')} disabled={Boolean(actionState.pending) || !isRunning}>
            <StopIcon size={16} />
            {t('dashboard.pauseMonitoring', 'Pause monitoring')}
          </button>
          <button className="dashboard-recovery-action" type="button" onClick={() => runAction('recover')} disabled={Boolean(actionState.pending) || isRunning}>
            <RestoreIcon size={16} />
            {t('dashboard.restoreWindows', 'Restore Windows settings')}
          </button>
        </div>
      </div>

      {actionState.error ? <div className="action-error">{actionState.error}</div> : null}

      <div className="dashboard-trust-strip" aria-label={t('dashboard.trustStatus', 'Safety and trust status')}>
        <div className={`dashboard-trust-item ${!hasSnapshot ? 'is-pending' : status.admin ? 'is-ready' : 'needs-attention'}`}>
          <span>{t('dashboard.admin', 'Admin')}</span>
          <strong>{!hasSnapshot ? t('common.na', 'N/A') : status.admin ? t('dashboard.yes', 'Yes') : t('dashboard.no', 'No')}</strong>
          <small>{hasSnapshot
            ? t('dashboard.adminTrustDetail', 'Required for protected Windows tuning')
            : t('dashboard.statusPending', 'Waiting for local status')}</small>
        </div>
        <div className={`dashboard-trust-item ${!hasSnapshot ? 'is-pending' : recoveryClean ? 'is-ready' : 'needs-attention'}`}>
          <span>{t('dashboard.recovery', 'Safe restore')}</span>
          <strong>{!hasSnapshot ? t('common.na', 'N/A') : recoveryClean ? t('checkStatus.ok', 'Ready') : t('checkStatus.warning', 'Review')}</strong>
          <small>{!hasSnapshot
            ? t('dashboard.statusPending', 'Waiting for local status')
            : recoveryClean
              ? t('dashboard.recoveryCleanDetail', 'Windows settings can be restored safely')
              : reportedFailureCount
                ? t('dashboard.recoveryAttentionDetail', '{{count}} recovery issues need review', { count: reportedFailureCount })
                : t('dashboard.recoveryReview', 'Review recovery status before starting')}</small>
        </div>
        <div className="dashboard-trust-item is-ready">
          <span>{t('dashboard.protectedProcesses', 'Protected processes')}</span>
          <strong>{t('process.status.protected', 'Protected')}</strong>
          <small>{t('dashboard.protectedProcessesDetail', 'Steam, FACEIT, anti-cheat, and system processes stay guarded')}</small>
        </div>
        <div className="dashboard-trust-item is-ready">
          <span>{t('dashboard.localControl', 'Local control')}</span>
          <strong>{t('dashboard.onDevice', 'On-device')}</strong>
          <small>{t('dashboard.localControlDetail', 'Lifecycle actions stay on this PC')}</small>
        </div>
      </div>

      <div className="kpi-strip dashboard-kpi-grid" aria-label="Dashboard KPI status">
        <KpiCell
          label={t('dashboard.trackedProcesses', 'Apps observed')}
          value={processCount}
          detail={formatProcessMode(snapshot?.process_mode, t)}
          highlight
        />
        <KpiCell
          label={t('dashboard.jailedBackground', 'Background limited')}
          value={status.jailed_process_count ?? 0}
          detail={status.background_jailing ? t('dashboard.backgroundJailingEnabled', 'Background control is ready') : t('dashboard.backgroundJailingDisabled', 'Background control is off')}
        />
        <KpiCell
          label={t('dashboard.powerPlan', 'Power Plan')}
          value={status.power_plan_active ? t('dashboard.active', 'ACTIVE') : t('dashboard.idle', 'IDLE')}
          detail={status.power_scheme_in_use || t('dashboard.waitingForGame', 'Waiting for a configured game')}
          tone={status.power_plan_active ? 'positive' : 'default'}
        />
        <KpiCell
          label={t('dashboard.timer', 'Timer')}
          value={timerValue}
          detail={t('dashboard.timerDetail', 'system timer resolution')}
          tone={status.timer_resolution_applied ? 'positive' : 'default'}
        />
        <KpiCell
          label={t('dashboard.cpuPartitions', 'CPU Partitions')}
          value={partitions}
          detail={status.topology_available ? t('dashboard.topologyAvailable', 'CPU map available') : t('dashboard.topologyStart', 'CPU allocation appears when monitoring is active')}
        />
        <KpiCell
          label={t('dashboard.compatibility', 'Compatibility')}
          value={capabilityMessages.length ? capabilityMessages.length : t('checkStatus.ok', 'Ready')}
          detail={capabilityMessages[0] || t('dashboard.fullFeatures', 'All features are available')}
          tone={capabilityMessages.length ? 'warning' : 'positive'}
        />
      </div>

      <div className="dashboard-insights">
        <SystemAnalysis live={live} />
        <ReadinessChecklist live={live} />
      </div>

      <ProcessTable snapshot={snapshot} />
    </section>
  );
});

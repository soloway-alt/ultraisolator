const DEFAULT_APP_SETTINGS = {
  language: 'en',
  launchAtWindowsStartup: false,
  minimizeToTrayOnStart: false,
  notificationToastsEnabled: true,
  firstRunCompleted: true
};

const DEFAULT_CONFIG = {
  games: ['cs2.exe', 'valorant.exe', 'dota2.exe'],
  auto_detect_steam_games: true,
  auto_detect_epic_games: true,
  auto_detect_gog_games: true,
  auto_detect_ea_games: true,
  auto_detect_battlenet_games: true,
  auto_detect_ubisoft_games: true,
  auto_detect_xbox_games: false,
  steam_library_paths: ['D:\\Games\\SteamLibrary'],
  epic_library_paths: [],
  protected_extra: ['obs64.exe', 'faceitclient.exe'],
  app_profiles: [
    {
      exe: 'obs64.exe',
      enabled: true,
      treat_as_game: false,
      never_jail: true,
      always_jail: false,
      priority_class: 'above_normal'
    }
  ],
  housekeeping_cores: 2,
  poll_interval_idle_ms: 1000,
  poll_interval_active_ms: 2000,
  enable_background_jailing: false,
  maintenance_jail_batch_size: 4,
  maintenance_jail_interval_ms: 30000,
  maintenance_jail_batch_cooldown_ms: 5000,
  enable_probalance: false,
  probalance_cpu_threshold_pct: 15,
  probalance_sustain_cycles: 4,
  probalance_restore_cycles: 3,
  enable_game_suggestions: true,
  disable_timer_resolution_tweak: false,
  disable_game_priority_boost: false,
  game_close_debounce_s: 3,
  game_exit_restore_delay_s: 10,
  gc_full_collect_interval_s: 1800,
  maintenance_skip_after_quiet_cycles: 3,
  log_file: '',
  anti_cheat_mode: 'conservative',
  event_backend: 'poll',
  allow_mmcss_injection: false,
  disable_power_scheme_switch: false
};

const CONFIG_SCHEMA = {
  games: { type: 'string_list', restart_required: true },
  auto_detect_steam_games: { type: 'bool', restart_required: true },
  auto_detect_epic_games: { type: 'bool', restart_required: true },
  auto_detect_gog_games: { type: 'bool', restart_required: true },
  auto_detect_ea_games: { type: 'bool', restart_required: true },
  auto_detect_battlenet_games: { type: 'bool', restart_required: true },
  auto_detect_ubisoft_games: { type: 'bool', restart_required: true },
  auto_detect_xbox_games: { type: 'bool', restart_required: true },
  steam_library_paths: { type: 'string_list', restart_required: true },
  epic_library_paths: { type: 'string_list', restart_required: true },
  protected_extra: { type: 'string_list', restart_required: true },
  app_profiles: {
    type: 'app_profiles',
    priority_choices: ['idle', 'below_normal', 'normal', 'above_normal', 'high'],
    restart_required: true
  },
  housekeeping_cores: { type: 'int', min: 1, max: 16, restart_required: true },
  poll_interval_idle_ms: { type: 'int', min: 50, max: 60000, restart_required: true },
  poll_interval_active_ms: { type: 'int', min: 50, max: 30000, restart_required: true },
  enable_background_jailing: { type: 'bool', restart_required: true },
  maintenance_jail_batch_size: { type: 'int', min: 1, max: 64, restart_required: true },
  maintenance_jail_interval_ms: { type: 'int', min: 5000, max: 300000, restart_required: true },
  maintenance_jail_batch_cooldown_ms: { type: 'int', min: 1000, max: 60000, restart_required: true },
  enable_probalance: { type: 'bool', restart_required: true },
  probalance_cpu_threshold_pct: { type: 'int', min: 1, max: 100, restart_required: true },
  probalance_sustain_cycles: { type: 'int', min: 1, max: 60, restart_required: true },
  probalance_restore_cycles: { type: 'int', min: 1, max: 60, restart_required: true },
  enable_game_suggestions: { type: 'bool', restart_required: true },
  disable_timer_resolution_tweak: { type: 'bool', restart_required: true },
  disable_game_priority_boost: { type: 'bool', restart_required: true },
  game_close_debounce_s: { type: 'int', min: 0, max: 60, restart_required: true },
  game_exit_restore_delay_s: { type: 'float', min: 0, max: 300, restart_required: true },
  gc_full_collect_interval_s: { type: 'float', min: 60, max: 86400, restart_required: true },
  maintenance_skip_after_quiet_cycles: { type: 'int', min: 0, max: 100, restart_required: true },
  log_file: { type: 'string', restart_required: true },
  anti_cheat_mode: { type: 'choice', choices: ['aggressive', 'conservative'], restart_required: true },
  event_backend: { type: 'choice', choices: ['poll'], restart_required: true },
  allow_mmcss_injection: { type: 'bool', restart_required: true },
  disable_power_scheme_switch: { type: 'bool', restart_required: true }
};

const PROCESSES = [
  {
    pid: 4242,
    name: 'cs2.exe',
    status: 'game',
    game: true,
    priority_class: 128,
    cpu_set_ids: [0, 1, 2, 3, 4, 5],
    source: 'configured',
    thread_count: 72,
    gen: 14,
    create_time: 1710000001
  },
  {
    pid: 6120,
    name: 'discord.exe',
    status: 'jailed',
    priority_class: 64,
    cpu_set_ids: [10, 11],
    source: 'background',
    thread_count: 32,
    gen: 9,
    create_time: 1710000002
  },
  {
    pid: 7316,
    name: 'steam.exe',
    status: 'protected',
    protected: true,
    priority_class: 32,
    cpu_set_ids: [],
    source: 'protected',
    thread_count: 21,
    gen: 6,
    create_time: 1710000003
  }
];

const SNAPSHOT = {
  process_mode: 'live',
  process_count: PROCESSES.length,
  processes: PROCESSES,
  game_suggestions: [
    {
      name: 'newgame.exe',
      pid: 5150,
      first_seen: 1710000004,
      signals: ['fullscreen', 'sustained_foreground']
    }
  ],
  status: {
    running: true,
    game_mode: true,
    admin: true,
    active_game_pids: [4242],
    tracked_process_count: PROCESSES.length,
    jailed_process_count: 1,
    background_jailing: false,
    timer_resolution_applied: 5000,
    power_plan_active: true,
    power_scheme_in_use: 'Ultimate Performance',
    topology_available: true,
    anti_cheat_mode: 'conservative',
    cpu_partitions: { game_cores: 6, background: 2, housekeeping: 2 },
    capability_notes: ['Background jailing is opt-in for this profile.']
  }
};

const ANALYSIS = {
  ok: true,
  available: true,
  score: 91,
  grade: 'excellent',
  summary: 'Competitive profile is ready for a monitored match.',
  categories: ['Control plane', 'CPU isolation', 'Latency tuning', 'System health'],
  boost_potential: { label: 'low', points: 4 },
  bottleneck: {
    available: false,
    label: 'Not estimated',
    reason: 'gpu_metrics_not_collected',
    detail: 'GPU and RAM telemetry are not collected in this MVP.'
  },
  checks: [
    { id: 'admin', label: 'Admin rights', status: 'ok', detail: 'Elevated shell is available.' },
    { id: 'topology', label: 'CPU topology', status: 'ok', detail: 'Topology map is available.' },
    { id: 'jailing', label: 'Background jailing', status: 'warning', detail: 'Background jailing is disabled by profile.' }
  ]
};

const READINESS = {
  available: true,
  summary: { ok: 3, warning: 1, error: 0, total: 4 },
  cache: { hit: false },
  checks: [
    { id: 'power_plan', label: 'Power plan', status: 'ok', detail: 'Ultimate Performance is active.' },
    { id: 'timer_resolution', label: 'Timer resolution', status: 'ok', detail: 'Timer resolution is applied.' },
    { id: 'background_jailing', label: 'Background jailing', status: 'warning', detail: 'Jailing is opt-in and disabled.' },
    { id: 'ifeo_priority', label: 'IFEO priority', status: 'ok', detail: 'Configured games are protected.' }
  ]
};

const CORES = Array.from({ length: 8 }, (_item, index) => {
  const partition = index < 4 ? 'game' : index < 6 ? 'background' : 'housekeeping';
  const efficiencyType = index < 6 ? 'performance' : 'efficiency';
  return {
    id: `core-${index}`,
    core_index: index,
    group: 0,
    llc_index: index < 4 ? 0 : 1,
    l3_size_bytes: index < 4 ? 33554432 : 16777216,
    efficiency_type: efficiencyType,
    efficiency_class: efficiencyType === 'performance' ? 8 : 2,
    parked: false,
    logical_indices: [index * 2, index * 2 + 1],
    logical_processor_count: 2,
    cpu_set_ids: [index * 2, index * 2 + 1],
    partition
  };
});

// Mirrors server/msi.py build_msi_payload.
const MSI = {
  ok: true,
  available: true,
  reason: null,
  readonly: true,
  restart_required: true,
  summary: { total: 3, enabled: 1, disabled: 1, unknown: 1 },
  devices: [
    {
      instance_id: 'PCI\\VEN_10DE&DEV_2684&SUBSYS_167C10DE&REV_A1\\4&2283f625&0&0019',
      name: 'NVIDIA GeForce RTX 4090',
      device_class: 'Display',
      msi_enabled: true,
      message_limit: 16
    },
    {
      instance_id: 'PCI\\VEN_8086&DEV_15F3&SUBSYS_00008086&REV_03\\3&11583659&0&FE',
      name: 'Intel(R) Ethernet Controller I225-V',
      device_class: 'Net',
      msi_enabled: false,
      message_limit: null
    },
    {
      instance_id: 'PCI\\VEN_1022&DEV_43F7&SUBSYS_33061B21&REV_01\\5&2c0cb4b3&0&280010',
      name: 'PCI device',
      device_class: 'PCI device',
      msi_enabled: null,
      message_limit: null
    }
  ],
  cache: { hit: false, ttl_s: 300, generated_at: 1710000000 }
};

// Mirrors server/log_store.py read_log_payload.
const LOGS = {
  ok: true,
  available: true,
  path: 'isolator.log',
  reason: null,
  limit: 500,
  size: 4096,
  modified_time: 1710000005,
  entries: [
    {
      line: 41,
      timestamp: '2024-03-09 17:20:01',
      severity: 'info',
      category: 'game',
      tag: 'INFO',
      message: 'Game detected: cs2.exe (pid 4242)',
      raw: '2024-03-09 17:20:01 [INFO] Game detected: cs2.exe (pid 4242)'
    },
    {
      line: 42,
      timestamp: '2024-03-09 17:20:02',
      severity: 'info',
      category: 'timer',
      tag: 'INFO',
      message: 'Timer resolution applied: 0.5 ms',
      raw: '2024-03-09 17:20:02 [INFO] Timer resolution applied: 0.5 ms'
    },
    {
      line: 43,
      timestamp: '2024-03-09 17:20:03',
      severity: 'warning',
      category: 'jail',
      tag: 'WARN',
      message: 'Background jailing is disabled by profile',
      raw: '2024-03-09 17:20:03 [WARN] Background jailing is disabled by profile'
    },
    {
      line: 44,
      timestamp: '2024-03-09 17:20:04',
      severity: 'error',
      category: 'power',
      tag: 'ERROR',
      message: 'Power scheme switch failed: access denied',
      raw: '2024-03-09 17:20:04 [ERROR] Power scheme switch failed: access denied'
    }
  ]
};

const TOPOLOGY = {
  ok: true,
  available: true,
  cores: CORES,
  llc_groups: [
    { id: 'llc-0', group: 0, llc_index: 0, l3_size_bytes: 33554432, core_ids: ['core-0', 'core-1', 'core-2', 'core-3'] },
    { id: 'llc-1', group: 0, llc_index: 1, l3_size_bytes: 16777216, core_ids: ['core-4', 'core-5', 'core-6', 'core-7'] }
  ],
  partitions: {
    game: { core_count: 4, logical_processor_count: 8 },
    background: { core_count: 2, logical_processor_count: 4 },
    housekeeping: { core_count: 2, logical_processor_count: 4 },
    unassigned: { core_count: 0, logical_processor_count: 0 }
  },
  summary: {
    core_count: 8,
    logical_processor_count: 16,
    heterogeneous_efficiency: true
  },
  refresh: { blocked_reason: null }
};

async function installRendererMock(page, options = {}) {
  await page.addInitScript(({ mockOptions }) => {
    const appSettings = mockOptions.appSettings;
    const defaultConfig = mockOptions.defaultConfig;
    const configSchema = mockOptions.configSchema;
    const snapshot = mockOptions.snapshot;
    const analysis = mockOptions.analysis;
    const readiness = mockOptions.readiness;
    const topology = mockOptions.topology;
    const msi = mockOptions.msi;
    const logs = mockOptions.logs;
    const listeners = new Set();
    const clone = (value) => JSON.parse(JSON.stringify(value));

    window.localStorage.setItem('eii_app_settings', JSON.stringify(appSettings));

    const emit = (eventName, data) => {
      for (const listener of Array.from(listeners)) {
        listener({ eventName, data });
      }
    };

    const backendRequest = async (request) => {
      if (mockOptions.backendUnavailable) {
        throw new Error('Mock backend unavailable');
      }
      switch (request.op) {
        case 'status.get':
          return clone(snapshot.status);
        case 'config.defaults.get':
          return { defaults: clone(defaultConfig), schema: clone(configSchema) };
        case 'config.get':
          return {
            config: clone(defaultConfig),
            exists: true,
            path: 'C:\\ProgramData\\Esports Isolator PRO\\config.json'
          };
        case 'config.update':
          return { config: clone(request.body?.config || defaultConfig), restart_required: false };
        case 'topology.get':
          return clone(topology);
        case 'analysis.get':
          return clone(analysis);
        case 'readiness.get':
          return clone(readiness);
        case 'msi.get':
          return clone(msi);
        case 'logs.get':
          return clone(logs);
        case 'lifecycle.start':
        case 'lifecycle.stop':
        case 'lifecycle.recover':
          return { ok: true };
        default:
          throw new Error(`${request.op} is not covered by the renderer visual mock.`);
      }
    };

    window.isolator = {
      backendRequest,
      getAppSettings: async () => clone(appSettings),
      updateAppSettings: async (settings) => ({ ...appSettings, ...settings }),
      onTrayShow: () => () => {},
      onLiveSnapshot: (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      startLiveSnapshot: async () => {
        if (mockOptions.backendUnavailable) {
          emit('state', { connectionState: 'error', error: 'Mock backend unavailable' });
          throw new Error('Mock backend unavailable');
        }
        setTimeout(() => {
          emit('state', { connectionState: 'connected' });
          emit('snapshot', JSON.stringify(snapshot));
        }, 0);
      },
      stopLiveSnapshot: async () => {}
    };
  }, {
    mockOptions: {
      backendUnavailable: Boolean(options.backendUnavailable),
      appSettings: { ...DEFAULT_APP_SETTINGS, ...options.appSettings },
      defaultConfig: DEFAULT_CONFIG,
      configSchema: CONFIG_SCHEMA,
      snapshot: SNAPSHOT,
      analysis: ANALYSIS,
      readiness: READINESS,
      topology: TOPOLOGY,
      msi: MSI,
      logs: LOGS
    }
  });
}

async function stabilizeRenderer(page) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
        caret-color: transparent !important;
      }
    `
  });
  await page.evaluate(() => document.fonts?.ready);
}

async function gotoMockedRenderer(page, hash, options = {}) {
  await installRendererMock(page, options);
  await page.goto(`/${hash}`);
  await stabilizeRenderer(page);
}

async function waitForAppReady(page, selector) {
  await page.locator(selector).waitFor({ state: 'visible' });
  await page.locator('.first-run-overlay').waitFor({ state: 'detached' }).catch(() => {});
}

function formatViolations(violations) {
  return violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    targets: violation.nodes.map((node) => node.target.join(' '))
  }));
}

module.exports = {
  DEFAULT_APP_SETTINGS,
  installRendererMock,
  gotoMockedRenderer,
  waitForAppReady,
  formatViolations
};

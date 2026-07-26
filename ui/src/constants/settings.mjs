export const APP_SETTINGS_STORAGE_KEY = 'eii_app_settings';

// The app-settings shape lives in the shared schema so the Electron main
// process and the renderer cannot drift; re-exported here for renderer code.
export {
  APP_SETTINGS_VERSION,
  DEFAULT_APP_SETTINGS,
  APP_SETTINGS_PATCH_KEYS as APP_SETTINGS_KEYS
} from '../../shared/app-settings-schema.mjs';

export const CONFIG_PRESETS = [
  {
    id: 'competitive',
    label: 'Competitive',
    detail: 'Fast game detection, active background control, and strict anti-cheat compatibility.',
    config: {
      poll_interval_active_ms: 2000,
      enable_background_jailing: true,
      anti_cheat_mode: 'aggressive',
      maintenance_jail_batch_size: 4,
      maintenance_jail_interval_ms: 30000,
      maintenance_jail_batch_cooldown_ms: 5000,
      housekeeping_cores: 1
    }
  },
  {
    id: 'casual',
    label: 'Casual',
    detail: 'Lower background activity with conservative game compatibility.',
    config: {
      poll_interval_active_ms: 5000,
      enable_background_jailing: false,
      anti_cheat_mode: 'conservative',
      maintenance_jail_batch_size: 2,
      maintenance_jail_interval_ms: 30000,
      maintenance_jail_batch_cooldown_ms: 5000,
      housekeeping_cores: 1
    }
  },
  {
    id: 'streaming',
    label: 'Streaming',
    detail: 'Keeps extra CPU room for capture, chat, and encoder apps.',
    config: {
      poll_interval_active_ms: 3000,
      enable_background_jailing: true,
      anti_cheat_mode: 'aggressive',
      maintenance_jail_batch_size: 3,
      maintenance_jail_interval_ms: 30000,
      maintenance_jail_batch_cooldown_ms: 5000,
      housekeeping_cores: 2
    }
  }
];

export const CONFIG_SECTIONS = [
  {
    id: 'games',
    title: 'Games & libraries',
    fields: ['games', 'auto_detect_steam_games', 'auto_detect_epic_games', 'steam_library_paths', 'epic_library_paths']
  },
  {
    id: 'background',
    title: 'Background isolation',
    fields: [
      'enable_background_jailing',
      'maintenance_jail_batch_size',
      'maintenance_jail_interval_ms',
      'maintenance_jail_batch_cooldown_ms',
      'maintenance_skip_after_quiet_cycles'
    ]
  },
  {
    id: 'detection',
    title: 'Detection & recovery',
    fields: [
      'poll_interval_active_ms',
      'poll_interval_idle_ms',
      'game_close_debounce_s',
      'game_exit_restore_delay_s'
    ]
  },
  {
    id: 'tuning',
    title: 'Game tuning',
    fields: [
      'housekeeping_cores',
      'disable_power_scheme_switch',
      'disable_timer_resolution_tweak',
      'disable_game_priority_boost',
      'anti_cheat_mode',
      'protected_extra'
    ]
  },
  {
    id: 'specialists',
    title: 'For specialists',
    fields: [
      'gc_full_collect_interval_s',
      'event_backend',
      'allow_mmcss_injection',
      'log_file'
    ]
  }
];

export const FIELD_LABELS = {
  games: 'Games',
  auto_detect_steam_games: 'Find Steam games automatically',
  auto_detect_epic_games: 'Find Epic games automatically',
  steam_library_paths: 'Steam library folders',
  epic_library_paths: 'Epic library folders',
  enable_background_jailing: 'Limit background apps while gaming',
  maintenance_jail_batch_size: 'Apps handled per pass',
  maintenance_jail_interval_ms: 'Background review interval',
  maintenance_jail_batch_cooldown_ms: 'Pause between background passes',
  maintenance_skip_after_quiet_cycles: 'Pause after quiet passes',
  poll_interval_active_ms: 'Game detection interval',
  poll_interval_idle_ms: 'Idle detection interval',
  housekeeping_cores: 'System-reserved CPU cores',
  disable_power_scheme_switch: 'Automatic performance power mode',
  disable_timer_resolution_tweak: 'Low-latency timer',
  disable_game_priority_boost: 'Game priority boost',
  game_close_debounce_s: 'Game close confirmation',
  game_exit_restore_delay_s: 'Restore delay after game',
  gc_full_collect_interval_s: 'Memory cleanup interval',
  anti_cheat_mode: 'Anti-cheat compatibility',
  protected_extra: 'Additional protected apps',
  log_file: 'Activity log file',
  event_backend: 'Process event source',
  allow_mmcss_injection: 'Windows multimedia scheduling integration'
};

export const POSITIVE_BOOLEAN_FIELDS = new Set([
  'disable_power_scheme_switch',
  'disable_timer_resolution_tweak',
  'disable_game_priority_boost'
]);

export const FIELD_HINTS = {
  games: 'One executable per line. Names without .exe are completed automatically.',
  steam_library_paths: 'One Steam library folder per line.',
  epic_library_paths: 'One Epic library folder per line.',
  protected_extra: 'Apps that must always remain unchanged, one name per line.',
  log_file: 'Leave empty to disable file logging.',
  allow_mmcss_injection: 'Advanced Windows multimedia scheduling option.'
};

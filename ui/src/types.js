// Types-only module: JSDoc typedefs for the payload shapes the renderer
// passes around. Zero runtime code — the `export {}` at the end just makes
// this file an ES module so `import('./types.js')` JSDoc references resolve
// in editors.

/**
 * Slice of useLiveSnapshot state each page receives (notifications stay out
 * so a notification frame does not re-render the memoized pages).
 * @typedef {object} LiveState
 * @property {string} connectionState - 'idle' | 'paused' | 'connected' | 'error'.
 * @property {?{status?: IsolatorStatus, processes: ProcessRow[], process_count?: number, process_mode?: string}} snapshot
 * @property {boolean} visible - Renderer window/document visibility.
 */

/**
 * snapshot.status payload from the engine — the fields the renderer reads.
 * @typedef {object} IsolatorStatus
 * @property {boolean} [monitoring_active] - Newer monitoring flag; `running` is the legacy fallback (see utils/status.mjs).
 * @property {boolean} [running] - Legacy monitoring flag.
 * @property {boolean} [game_mode]
 * @property {boolean} [admin]
 * @property {number} [tracked_process_count]
 * @property {number} [jailed_process_count]
 * @property {number[]} [active_game_pids]
 * @property {ProcessRow[]} [active_games]
 * @property {Array<string|{code?: string, key?: string, severity?: string, message?: string, message_key?: string, detail?: string, data?: object}>} [capability_issues]
 * @property {string[]} [capability_notes]
 * @property {number} [reported_failure_count]
 * @property {boolean} [persistent_recovery_incomplete]
 * @property {object} [cpu_partitions] - Partition name -> core info (see formatPartitions).
 * @property {number|string} [timer_resolution_applied]
 * @property {string} [anti_cheat_mode] - 'aggressive' | 'conservative'.
 * @property {object} [config] - Effective engine config (disable_* flags read on Dashboard).
 * @property {boolean} [background_jailing]
 * @property {boolean} [power_plan_active]
 * @property {string} [power_scheme_in_use]
 * @property {boolean} [topology_available]
 */

/**
 * One entry of snapshot.processes / status.active_games.
 * @typedef {object} ProcessRow
 * @property {number} pid
 * @property {string} [name]
 * @property {boolean} [game]
 * @property {string} [status] - 'game' | 'jailed' | 'foreground' | 'protected' | 'tracked'.
 * @property {string} [source] - e.g. 'observed_game'.
 * @property {string} [tuning_state] - 'pending' | 'applied' | 'skipped' | 'blocked' | 'failed'.
 * @property {boolean} [protected]
 * @property {number} [priority_class]
 * @property {number[]} [cpu_set_ids]
 * @property {number} [affinity_mask]
 * @property {number} [create_time]
 */

/**
 * One /api/config/defaults schema entry, discriminated by `type`.
 * @typedef {object} ConfigFieldSpec
 * @property {'bool'|'int'|'float'|'choice'|'string'|'string_list'|'app_profiles'} type
 * @property {string[]} [choices] - For type 'choice'.
 * @property {number} [min] - For types 'int' / 'float'.
 * @property {number} [max] - For types 'int' / 'float'.
 * @property {string[]} [priority_choices] - For type 'app_profiles'.
 * @property {boolean} [restart_required]
 */

/**
 * One readiness (/api/readiness) or analysis (/api/analysis) check.
 * @typedef {object} Check
 * @property {string} id
 * @property {string} label
 * @property {string} status - 'ok' | 'warning' | 'error' | 'info'.
 * @property {string} detail
 * @property {object} [data] - Interpolation params for the detail locale key.
 */

/**
 * One PAGES navigation entry (constants/navigation.js).
 * @typedef {object} PageEntry
 * @property {string} id
 * @property {string} label
 * @property {string} labelKey
 * @property {string} title
 * @property {import('react').ComponentType} renderIcon
 */

export {};

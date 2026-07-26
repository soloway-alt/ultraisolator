// Single canonical table of backend operations shared by the Electron main
// process (IPC proxy allowlist) and the renderer (REST-path translation).
// Loaded from CommonJS via synchronous require(esm) in electron-main.js and
// via import in ui/src/utils/api.mjs.

export const BACKEND_OPERATIONS = Object.freeze({
  'status.get': Object.freeze({ method: 'GET', path: '/api/status' }),
  'config.defaults.get': Object.freeze({ method: 'GET', path: '/api/config/defaults' }),
  'config.get': Object.freeze({ method: 'GET', path: '/api/config' }),
  'config.update': Object.freeze({ method: 'PUT', path: '/api/config', body: true }),
  'topology.get': Object.freeze({ method: 'GET', path: '/api/topology', booleanParam: 'refresh' }),
  'analysis.get': Object.freeze({ method: 'GET', path: '/api/analysis' }),
  'readiness.get': Object.freeze({ method: 'GET', path: '/api/readiness', booleanParam: 'refresh' }),
  'msi.get': Object.freeze({ method: 'GET', path: '/api/msi', booleanParam: 'refresh' }),
  'logs.get': Object.freeze({ method: 'GET', path: '/api/logs', integerParam: 'limit', min: 1, max: 500 }),
  'lifecycle.start': Object.freeze({ method: 'POST', path: '/api/start' }),
  'lifecycle.stop': Object.freeze({ method: 'POST', path: '/api/stop' }),
  'lifecycle.recover': Object.freeze({ method: 'POST', path: '/api/recover' })
});

// `${method} ${path}` -> { op, booleanParam?, integerParam?, min?, max?, body? }
export const ROUTE_INDEX = Object.freeze(Object.fromEntries(
  Object.entries(BACKEND_OPERATIONS).map(([op, { method, path, ...rest }]) => [
    `${method} ${path}`,
    Object.freeze({ op, ...rest })
  ])
));

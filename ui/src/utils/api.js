function parseJsonBody(body, method, path) {
  if (body === undefined || body === null || body === '') {
    return undefined;
  }
  if (typeof body === 'string') {
    try {
      return JSON.parse(body);
    } catch (_error) {
      throw new Error(`${method} ${path} request body must be valid JSON.`);
    }
  }
  if (typeof body === 'object' && !Array.isArray(body)) {
    return body;
  }
  throw new Error(`${method} ${path} request body must be a JSON object.`);
}

function requireNoUnexpectedQuery(url, allowedNames, path) {
  for (const name of url.searchParams.keys()) {
    if (!allowedNames.includes(name)) {
      throw new Error(`Unsupported query parameter for ${path}: ${name}`);
    }
  }
}

function booleanParam(url, name, path) {
  if (!url.searchParams.has(name)) {
    return undefined;
  }
  const value = url.searchParams.get(name);
  if (value !== '0' && value !== '1') {
    throw new Error(`${name} must be 0 or 1 for ${path}.`);
  }
  return value === '1';
}

function integerParam(url, name, path) {
  if (!url.searchParams.has(name)) {
    return undefined;
  }
  const value = Number(url.searchParams.get(name));
  if (!Number.isInteger(value)) {
    throw new Error(`${name} must be an integer for ${path}.`);
  }
  return value;
}

function operationForRequest(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const url = new URL(path, 'http://isolator.local');
  const route = url.pathname;

  if (method === 'GET' && route === '/api/status') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'status.get' };
  }
  if (method === 'GET' && route === '/api/config/defaults') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'config.defaults.get' };
  }
  if (method === 'GET' && route === '/api/config') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'config.get' };
  }
  if (method === 'PUT' && route === '/api/config') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'config.update', body: parseJsonBody(options.body, method, path) };
  }
  if (method === 'GET' && route === '/api/topology') {
    requireNoUnexpectedQuery(url, ['refresh'], path);
    return { op: 'topology.get', params: { refresh: booleanParam(url, 'refresh', path) === true } };
  }
  if (method === 'GET' && route === '/api/analysis') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'analysis.get' };
  }
  if (method === 'GET' && route === '/api/readiness') {
    requireNoUnexpectedQuery(url, ['refresh'], path);
    return { op: 'readiness.get', params: { refresh: booleanParam(url, 'refresh', path) === true } };
  }
  if (method === 'GET' && route === '/api/msi') {
    requireNoUnexpectedQuery(url, ['refresh'], path);
    return { op: 'msi.get', params: { refresh: booleanParam(url, 'refresh', path) === true } };
  }
  if (method === 'GET' && route === '/api/logs') {
    requireNoUnexpectedQuery(url, ['limit'], path);
    const limit = integerParam(url, 'limit', path);
    // Omit the key entirely when absent: `{limit: undefined}` survives the
    // IPC structured clone as an own property and the main-process validator
    // would reject it instead of applying the backend default.
    return limit === undefined ? { op: 'logs.get' } : { op: 'logs.get', params: { limit } };
  }
  if (method === 'POST' && route === '/api/start') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'lifecycle.start' };
  }
  if (method === 'POST' && route === '/api/stop') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'lifecycle.stop' };
  }
  if (method === 'POST' && route === '/api/recover') {
    requireNoUnexpectedQuery(url, [], path);
    return { op: 'lifecycle.recover' };
  }
  throw new Error(`${method} ${path} is not an allowed backend operation.`);
}

function raiseForPayload(payload, method, path, status) {
  if (payload?.ok === false) {
    const error = new Error(payload.error || `${method} ${path} failed`);
    error.payload = payload;
    if (status) {
      error.status = status;
    }
    throw error;
  }
}

export async function requestJson(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  // Fail fast and locally on unsupported options. `headers` in particular is
  // treated as an attack signal by the main-process IPC validator, so a call
  // site passing it must break here in development, not at the trust boundary.
  for (const key of Object.keys(options)) {
    if (key !== 'method' && key !== 'body') {
      throw new Error(`Unsupported requestJson option: ${key}`);
    }
  }
  if (!window.isolator?.backendRequest) {
    throw new Error('Electron backend proxy is unavailable.');
  }

  const payload = await window.isolator.backendRequest(operationForRequest(path, options));
  raiseForPayload(payload, method, path);
  return payload || {};
}

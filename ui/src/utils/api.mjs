import { ROUTE_INDEX } from '../../shared/backend-operations.mjs';

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

export function operationForRequest(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const url = new URL(path, 'http://isolator.local');
  const route = ROUTE_INDEX[`${method} ${url.pathname}`];

  if (!route) {
    throw new Error(`${method} ${path} is not an allowed backend operation.`);
  }
  requireNoUnexpectedQuery(url, [route.booleanParam, route.integerParam].filter(Boolean), path);
  if (route.body) {
    return { op: route.op, body: parseJsonBody(options.body, method, path) };
  }
  if (route.booleanParam) {
    return { op: route.op, params: { [route.booleanParam]: booleanParam(url, route.booleanParam, path) === true } };
  }
  if (route.integerParam) {
    const value = integerParam(url, route.integerParam, path);
    // Omit the key entirely when absent: `{limit: undefined}` survives the
    // IPC structured clone as an own property and the main-process validator
    // would reject it instead of applying the backend default.
    return value === undefined ? { op: route.op } : { op: route.op, params: { [route.integerParam]: value } };
  }
  return { op: route.op };
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

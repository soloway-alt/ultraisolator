// Validation for the renderer -> backend IPC proxy. Pure request-shape logic
// with no Electron imports so the trust boundary is unit-testable; the caller
// (electron-main.js) supplies sender authentication and the HTTP transport.
// Canonical operation table shared with the renderer; Electron 42's Node
// supports synchronous require() of a synchronous ES module graph.
const { BACKEND_OPERATIONS } = require('../shared/backend-operations.mjs');

const MAX_PROXY_BODY_BYTES = 64 * 1024;

function proxyError(code, message) {
  const error = new Error(`${code}: ${message}`);
  error.code = code;
  return error;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function validateNoExtraRequestKeys(request) {
  const allowedKeys = new Set(['op', 'params', 'body']);
  for (const key of Object.keys(request)) {
    if (key === 'headers') {
      throw proxyError('invalid_headers', 'Renderer-supplied backend headers are not allowed.');
    }
    if (!allowedKeys.has(key)) {
      throw proxyError('invalid_body', `Unsupported backend proxy field: ${key}`);
    }
  }
}

function appendBooleanParam(pathValue, params, name) {
  // Treat an explicit-undefined value the same as an absent key; structured
  // clone preserves `{name: undefined}` as an own property across IPC.
  if (!params || params[name] === undefined) {
    return pathValue;
  }
  if (typeof params[name] !== 'boolean') {
    throw proxyError('invalid_query', `${name} must be a boolean.`);
  }
  return params[name] ? `${pathValue}?${name}=1` : pathValue;
}

function appendIntegerParam(pathValue, params, name, min, max) {
  if (!params || params[name] === undefined) {
    return pathValue;
  }
  const value = params[name];
  if (!Number.isInteger(value) || value < min || value > max) {
    throw proxyError('invalid_query', `${name} must be an integer from ${min} to ${max}.`);
  }
  return `${pathValue}?${name}=${value}`;
}

function validateOperationParams(definition, params) {
  const allowed = new Set([definition.booleanParam, definition.integerParam].filter(Boolean));
  if (params === undefined) {
    return {};
  }
  if (!isPlainObject(params)) {
    throw proxyError('invalid_query', 'Backend proxy params must be an object.');
  }
  for (const key of Object.keys(params)) {
    if (!allowed.has(key)) {
      throw proxyError('invalid_query', `Unsupported backend proxy query parameter: ${key}`);
    }
  }
  return params;
}

function validateOperationBody(definition, body) {
  if (!definition.body) {
    if (body !== undefined) {
      throw proxyError('invalid_body', 'This backend operation does not accept a body.');
    }
    return undefined;
  }
  if (!isPlainObject(body) || !isPlainObject(body.config)) {
    throw proxyError('invalid_body', 'Config updates must use a JSON object body with a config object.');
  }
  if (Buffer.byteLength(JSON.stringify(body), 'utf8') > MAX_PROXY_BODY_BYTES) {
    throw proxyError('body_too_large', 'Backend proxy body exceeds 64 KiB.');
  }
  return body;
}

function resolveBackendOperation(request = {}, operations = BACKEND_OPERATIONS) {
  if (!isPlainObject(request)) {
    throw proxyError('invalid_body', 'Backend proxy request must be an object.');
  }
  validateNoExtraRequestKeys(request);
  const definition = operations[request.op];
  if (!definition) {
    throw proxyError('not_found', 'unknown backend operation');
  }

  const params = validateOperationParams(definition, request.params);
  let urlPath = definition.path;
  if (definition.booleanParam) {
    urlPath = appendBooleanParam(urlPath, params, definition.booleanParam);
  }
  if (definition.integerParam) {
    urlPath = appendIntegerParam(urlPath, params, definition.integerParam, definition.min, definition.max);
  }

  return {
    method: definition.method,
    path: urlPath,
    body: validateOperationBody(definition, request.body)
  };
}

module.exports = {
  MAX_PROXY_BODY_BYTES,
  isPlainObject,
  proxyError,
  resolveBackendOperation
};

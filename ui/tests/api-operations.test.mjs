import assert from 'node:assert/strict';
import test from 'node:test';
import { BACKEND_OPERATIONS, ROUTE_INDEX } from '../shared/backend-operations.mjs';
import { operationForRequest } from '../src/utils/api.mjs';

const SAMPLE_CONFIG_BODY = { config: { games: ['cs2.exe'] } };

test('every backend operation round-trips through operationForRequest', () => {
  for (const [op, definition] of Object.entries(BACKEND_OPERATIONS)) {
    const options = { method: definition.method };
    let path = definition.path;
    let expected = { op };
    if (definition.body) {
      options.body = SAMPLE_CONFIG_BODY;
      expected = { op, body: SAMPLE_CONFIG_BODY };
    }
    if (definition.booleanParam) {
      path = `${definition.path}?${definition.booleanParam}=1`;
      expected = { op, params: { [definition.booleanParam]: true } };
    }
    if (definition.integerParam) {
      path = `${definition.path}?${definition.integerParam}=${definition.min}`;
      expected = { op, params: { [definition.integerParam]: definition.min } };
    }
    assert.deepEqual(operationForRequest(path, options), expected, `${definition.method} ${path}`);
  }
});

test('boolean-param routes report false params when the query is omitted', () => {
  for (const [op, definition] of Object.entries(BACKEND_OPERATIONS)) {
    if (!definition.booleanParam) {
      continue;
    }
    assert.deepEqual(
      operationForRequest(definition.path, { method: definition.method }),
      { op, params: { [definition.booleanParam]: false } }
    );
  }
});

test('unknown routes are rejected', () => {
  assert.throws(
    () => operationForRequest('/api/unknown'),
    /GET \/api\/unknown is not an allowed backend operation\./
  );
});

test('unknown verbs on known routes are rejected', () => {
  assert.throws(
    () => operationForRequest('/api/status', { method: 'DELETE' }),
    /DELETE \/api\/status is not an allowed backend operation\./
  );
  assert.throws(
    () => operationForRequest('/api/start', { method: 'GET' }),
    /GET \/api\/start is not an allowed backend operation\./
  );
});

test('unexpected query parameters are rejected', () => {
  assert.throws(
    () => operationForRequest('/api/status?refresh=1'),
    /Unsupported query parameter for \/api\/status\?refresh=1: refresh/
  );
  assert.throws(
    () => operationForRequest('/api/logs?refresh=1'),
    /Unsupported query parameter for \/api\/logs\?refresh=1: refresh/
  );
  assert.throws(
    () => operationForRequest('/api/config?limit=5', { method: 'PUT', body: SAMPLE_CONFIG_BODY }),
    /Unsupported query parameter for \/api\/config\?limit=5: limit/
  );
});

test('/api/logs without a limit omits the params key entirely', () => {
  const operation = operationForRequest('/api/logs');
  assert.deepEqual(operation, { op: 'logs.get' });
  assert.equal(Object.prototype.hasOwnProperty.call(operation, 'params'), false);
});

test('non-integer log limits are rejected', () => {
  assert.throws(
    () => operationForRequest('/api/logs?limit=abc'),
    /limit must be an integer for \/api\/logs\?limit=abc\./
  );
  assert.throws(
    () => operationForRequest('/api/logs?limit=2.5'),
    /limit must be an integer for \/api\/logs\?limit=2\.5\./
  );
});

test('every op reachable from operationForRequest exists in BACKEND_OPERATIONS', () => {
  for (const [key, entry] of Object.entries(ROUTE_INDEX)) {
    const [method, routePath] = key.split(' ');
    const options = { method };
    if (entry.body) {
      options.body = SAMPLE_CONFIG_BODY;
    }
    const resolved = operationForRequest(routePath, options);
    assert.ok(
      Object.prototype.hasOwnProperty.call(BACKEND_OPERATIONS, resolved.op),
      `${key} resolved to unknown op ${resolved.op}`
    );
    assert.equal(resolved.op, entry.op);
  }
});

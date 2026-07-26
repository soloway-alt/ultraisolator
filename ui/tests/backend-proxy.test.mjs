import assert from 'node:assert/strict';
import test from 'node:test';
import backendProxy from '../main/backend-proxy.js';

const { MAX_PROXY_BODY_BYTES, resolveBackendOperation } = backendProxy;

function codeOf(fn) {
  try {
    fn();
  } catch (error) {
    return error.code;
  }
  throw new Error('expected the call to throw');
}

test('non-object requests and unknown operations are rejected', () => {
  assert.equal(codeOf(() => resolveBackendOperation(null)), 'invalid_body');
  assert.equal(codeOf(() => resolveBackendOperation([])), 'invalid_body');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'nope.get' })), 'not_found');
  assert.equal(codeOf(() => resolveBackendOperation({})), 'not_found');
});

test('renderer-supplied headers and extra fields are rejected', () => {
  assert.equal(
    codeOf(() => resolveBackendOperation({ op: 'status.get', headers: { Authorization: 'Bearer x' } })),
    'invalid_headers'
  );
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'status.get', url: '/api/status' })), 'invalid_body');
});

test('bodies are only accepted where declared and capped at 64 KiB', () => {
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'status.get', body: {} })), 'invalid_body');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'config.update', body: { config: [] } })), 'invalid_body');

  const resolved = resolveBackendOperation({ op: 'config.update', body: { config: { games: ['cs2.exe'] } } });
  assert.deepEqual(resolved, { method: 'PUT', path: '/api/config', body: { config: { games: ['cs2.exe'] } } });

  const oversized = { config: { log_file: 'x'.repeat(MAX_PROXY_BODY_BYTES) } };
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'config.update', body: oversized })), 'body_too_large');
});

test('integer params enforce the declared 1..500 bounds', () => {
  assert.equal(resolveBackendOperation({ op: 'logs.get', params: { limit: 1 } }).path, '/api/logs?limit=1');
  assert.equal(resolveBackendOperation({ op: 'logs.get', params: { limit: 500 } }).path, '/api/logs?limit=500');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'logs.get', params: { limit: 0 } })), 'invalid_query');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'logs.get', params: { limit: 501 } })), 'invalid_query');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'logs.get', params: { limit: 2.5 } })), 'invalid_query');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'logs.get', params: { limit: '5' } })), 'invalid_query');
});

test('boolean params must be real booleans and serialize as ?name=1', () => {
  assert.equal(resolveBackendOperation({ op: 'topology.get', params: { refresh: true } }).path, '/api/topology?refresh=1');
  assert.equal(resolveBackendOperation({ op: 'topology.get', params: { refresh: false } }).path, '/api/topology');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'topology.get', params: { refresh: 1 } })), 'invalid_query');
  assert.equal(codeOf(() => resolveBackendOperation({ op: 'topology.get', params: { refresh: 'true' } })), 'invalid_query');
});

test('explicit-undefined params behave like absent params', () => {
  // Structured clone keeps `{refresh: undefined}` as an own property across IPC.
  assert.equal(resolveBackendOperation({ op: 'topology.get', params: { refresh: undefined } }).path, '/api/topology');
  assert.equal(resolveBackendOperation({ op: 'logs.get', params: { limit: undefined } }).path, '/api/logs');
  assert.equal(resolveBackendOperation({ op: 'status.get' }).path, '/api/status');
  assert.equal(
    codeOf(() => resolveBackendOperation({ op: 'status.get', params: { unexpected: undefined } })),
    'invalid_query'
  );
});

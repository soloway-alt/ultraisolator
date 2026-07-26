import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import liveStream from '../main/live-stream.js';

const { createLiveStreamRelay, parseSseFrame } = liveStream;

const RECONNECT_MS = 5;

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class FakeResponse extends EventEmitter {
  constructor(statusCode) {
    super();
    this.statusCode = statusCode;
    this.resumed = false;
  }

  resume() {
    this.resumed = true;
  }

  setEncoding() {}
}

class FakeRequest extends EventEmitter {
  constructor() {
    super();
    this.destroyed = false;
  }

  destroy() {
    this.destroyed = true;
  }
}

// Builds a relay whose httpGet hands out scripted responses; like the real
// http.get, the response callback fires asynchronously.
function makeRelay({ statusCodes = [200], backendUrl = 'http://127.0.0.1:8000' } = {}) {
  const state = { events: [], statuses: [], requests: [], responses: [] };
  const relay = createLiveStreamRelay({
    httpGet: (options, onResponse) => {
      const request = new FakeRequest();
      const response = new FakeResponse(statusCodes[Math.min(state.requests.length, statusCodes.length - 1)]);
      state.requests.push({ options, request });
      state.responses.push(response);
      queueMicrotask(() => onResponse(response));
      return request;
    },
    getBackendUrl: () => backendUrl,
    getAuthToken: () => 'test-token',
    emit: (payload) => state.events.push(payload),
    onSnapshotStatus: (status) => state.statuses.push(status),
    reconnectDelayMs: RECONNECT_MS
  });
  return { relay, state };
}

function connectionStates(state) {
  return state.events.filter((event) => event.eventName === 'state').map((event) => event.data.connectionState);
}

test('parseSseFrame reads the event name and joins multi-line data', () => {
  assert.deepEqual(parseSseFrame('event: snapshot\ndata: {"a":1}'), { eventName: 'snapshot', data: '{"a":1}' });
  assert.deepEqual(parseSseFrame('data: one\ndata: two'), { eventName: 'message', data: 'one\ntwo' });
  assert.deepEqual(parseSseFrame(': comment only'), { eventName: 'message', data: '' });
});

test('a connected stream relays frames and feeds snapshot status to the tray', async () => {
  const { relay, state } = makeRelay();
  relay.start();
  await tick();

  assert.equal(state.requests.length, 1);
  assert.equal(state.requests[0].options.path, '/api/live');
  assert.equal(state.requests[0].options.headers.Authorization, 'Bearer test-token');

  const response = state.responses[0];
  // The frame arrives split across two chunks to exercise buffering.
  response.emit('data', 'event: snapshot\ndata: {"status":{"running":true}}');
  response.emit('data', '\n\nevent: notification\ndata: {}\n\n');
  assert.deepEqual(state.statuses, [{ running: true }]);
  assert.deepEqual(connectionStates(state), ['connecting', 'connected']);
  assert.deepEqual(
    state.events.filter((event) => event.eventName !== 'state').map((event) => event.eventName),
    ['snapshot', 'notification']
  );
  relay.stop({ notify: false });
});

test('a malformed snapshot frame reports an error instead of relaying', async () => {
  const { relay, state } = makeRelay();
  relay.start();
  await tick();

  state.responses[0].emit('data', 'event: snapshot\ndata: {broken\n\n');
  assert.deepEqual(state.statuses, []);
  assert.equal(state.events.filter((event) => event.eventName === 'snapshot').length, 0);
  assert.ok(state.events.some((event) => event.data?.error === 'malformed live frame'));
  relay.stop({ notify: false });
});

test('401 and 403 responses surface an error and never reconnect', async () => {
  for (const statusCode of [401, 403]) {
    const { relay, state } = makeRelay({ statusCodes: [statusCode] });
    relay.start();
    await tick();
    // Wait long enough that a scheduled reconnect would have fired.
    await sleep(RECONNECT_MS * 6);

    assert.equal(state.requests.length, 1, `HTTP ${statusCode} must not retry`);
    assert.equal(state.responses[0].resumed, true);
    const last = state.events.at(-1);
    assert.equal(last.data.connectionState, 'error');
    assert.equal(last.data.error, `live stream failed with HTTP ${statusCode}`);
    relay.stop({ notify: false });
  }
});

test('other HTTP failures schedule a reconnect', async () => {
  const { relay, state } = makeRelay({ statusCodes: [500, 200] });
  relay.start();
  await tick();
  await sleep(RECONNECT_MS * 6);

  assert.ok(state.requests.length >= 2, '500 must schedule a retry');
  assert.ok(state.events.some((event) => event.data?.error === 'live stream failed with HTTP 500'));
  assert.equal(connectionStates(state).at(-1), 'connected');
  relay.stop({ notify: false });
});

test('stream end and request errors reconnect while running', async () => {
  const { relay, state } = makeRelay({ statusCodes: [200, 200] });
  relay.start();
  await tick();
  state.responses[0].emit('end');
  await sleep(RECONNECT_MS * 6);

  assert.ok(state.requests.length >= 2, 'a dropped stream must reconnect');
  assert.ok(state.events.some((event) => event.data?.error === 'live stream disconnected'));
  relay.stop({ notify: false });
});

test('stop destroys the request, notifies by default, and stays silent when asked', async () => {
  const first = makeRelay();
  first.relay.start();
  await tick();
  first.relay.stop();
  assert.equal(first.state.requests[0].request.destroyed, true);
  assert.equal(first.state.events.at(-1).data.connectionState, 'paused');
  // No reconnect after stop.
  await sleep(RECONNECT_MS * 6);
  assert.equal(first.state.requests.length, 1);

  const second = makeRelay();
  second.relay.start();
  await tick();
  second.relay.stop({ notify: false });
  assert.ok(!second.state.events.some((event) => event.data?.connectionState === 'paused'));
});

test('a missing backend URL keeps retrying until one appears', async () => {
  let backendUrl = null;
  const state = { events: [], requests: 0 };
  const relay = createLiveStreamRelay({
    httpGet: (_options, onResponse) => {
      state.requests += 1;
      const request = new FakeRequest();
      queueMicrotask(() => onResponse(new FakeResponse(200)));
      return request;
    },
    getBackendUrl: () => backendUrl,
    getAuthToken: () => 'test-token',
    emit: (payload) => state.events.push(payload),
    onSnapshotStatus: () => {},
    reconnectDelayMs: RECONNECT_MS
  });
  relay.start();
  assert.ok(state.events.some((event) => event.data?.error === 'Backend is not ready.'));
  backendUrl = 'http://127.0.0.1:8000';
  await sleep(RECONNECT_MS * 6);
  assert.ok(state.requests >= 1, 'the retry must connect once the backend URL exists');
  relay.stop({ notify: false });
});

import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import supervisor from '../main/backend-supervisor.js';

const {
  createBackendJsonClient,
  findFreePort,
  forceKillProcessTree,
  restartDelayMs,
  waitForBackendReady
} = supervisor;

function listen(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => {
      resolve({ server, url: `http://127.0.0.1:${server.address().port}` });
    });
  });
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test('restartDelayMs backs off linearly and caps at 8 seconds', () => {
  assert.equal(restartDelayMs(1), 1000);
  assert.equal(restartDelayMs(4), 4000);
  assert.equal(restartDelayMs(8), 8000);
  assert.equal(restartDelayMs(50), 8000);
});

test('findFreePort returns a bindable loopback port', async () => {
  const port = await findFreePort();
  assert.ok(Number.isInteger(port) && port > 0 && port < 65536);
});

test('the JSON client authenticates, parses, and unwraps backend errors', async () => {
  const seen = [];
  const { server, url } = await listen((request, response) => {
    seen.push({ path: request.url, auth: request.headers.authorization });
    if (request.url === '/api/ok') {
      response.end(JSON.stringify({ ok: true, value: 7 }));
    } else if (request.url === '/api/refused') {
      response.statusCode = 403;
      response.end(JSON.stringify({ ok: false, error: 'not allowed' }));
    } else {
      response.end('this is not json');
    }
  });
  try {
    const client = createBackendJsonClient({
      getBackendUrl: () => url,
      getAuthToken: () => 'secret-token'
    });

    assert.deepEqual(await client.requestJson('/api/ok'), { ok: true, value: 7 });
    assert.equal(seen[0].auth, 'Bearer secret-token');

    await assert.rejects(client.requestJson('/api/refused'), (error) => {
      assert.equal(error.message, 'not allowed');
      assert.equal(error.status, 403);
      return true;
    });

    await assert.rejects(client.requestJson('/api/garbage'), /returned non-JSON response/);
  } finally {
    await close(server);
  }
});

test('the JSON client rejects immediately when no backend URL exists', async () => {
  const client = createBackendJsonClient({ getBackendUrl: () => null, getAuthToken: () => 'x' });
  await assert.rejects(client.requestJson('/api/status'), /Backend is not ready/);
});

test('waitForBackendReady resolves once /api/status answers 200', async () => {
  let calls = 0;
  const { server, url } = await listen((request, response) => {
    calls += 1;
    assert.equal(request.headers.authorization, 'Bearer ready-token');
    response.statusCode = calls < 3 ? 503 : 200;
    response.end();
  });
  try {
    await waitForBackendReady(url, 'ready-token', 5000);
    assert.ok(calls >= 3);
  } finally {
    await close(server);
  }
});

test('waitForBackendReady rejects when the deadline passes', async () => {
  const { server, url } = await listen((_request, response) => {
    response.statusCode = 503;
    response.end();
  });
  try {
    await assert.rejects(waitForBackendReady(url, 'x', 400), /did not become ready/);
  } finally {
    await close(server);
  }
});

function fakeChild({ pid = 4321, exited = false } = {}) {
  return {
    pid,
    exitCode: exited ? 0 : null,
    signalCode: null,
    kills: [],
    kill(signal) {
      this.kills.push(signal ?? 'default');
    }
  };
}

test('forceKillProcessTree uses taskkill /T /F on Windows and SIGKILL elsewhere', () => {
  const spawned = [];
  const winChild = fakeChild();
  forceKillProcessTree(winChild, {
    platform: 'win32',
    spawnFn: (command, args) => spawned.push({ command, args })
  });
  assert.deepEqual(spawned, [{ command: 'taskkill', args: ['/pid', '4321', '/T', '/F'] }]);
  assert.deepEqual(winChild.kills, []);

  const unixChild = fakeChild();
  forceKillProcessTree(unixChild, { platform: 'linux', spawnFn: () => {} });
  assert.deepEqual(unixChild.kills, ['SIGKILL']);
});

test('forceKillProcessTree falls back to SIGKILL when taskkill cannot spawn and skips exited children', () => {
  const child = fakeChild();
  forceKillProcessTree(child, {
    platform: 'win32',
    spawnFn: () => {
      throw new Error('spawn failed');
    }
  });
  assert.deepEqual(child.kills, ['SIGKILL']);

  const exited = fakeChild({ exited: true });
  const spawned = [];
  forceKillProcessTree(exited, { platform: 'win32', spawnFn: (...call) => spawned.push(call) });
  assert.deepEqual(spawned, []);
  assert.deepEqual(exited.kills, []);
});

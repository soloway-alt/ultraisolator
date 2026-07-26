// Backend process plumbing that needs no Electron imports: the authenticated
// JSON client, readiness polling, port discovery, the single-spawn attempt
// with ENOENT-safe error handling, the restart backoff, and the Windows
// process-tree kill escalation. electron-main.js owns process state and
// wires these together.
const { spawn } = require('child_process');
const http = require('http');
const net = require('net');

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function createBackendJsonClient({ getBackendUrl, getAuthToken }) {
  function requestJson(urlPath, options = {}) {
    return new Promise((resolve, reject) => {
      const backendUrl = getBackendUrl();
      if (!backendUrl) {
        reject(new Error('Backend is not ready.'));
        return;
      }
      const method = String(options.method || 'GET').toUpperCase();
      const bodyText = options.body === undefined ? null : JSON.stringify(options.body);
      const url = new URL(urlPath, backendUrl);
      const request = http.request({
        method,
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        timeout: options.timeout || 2000,
        headers: {
          Authorization: `Bearer ${getAuthToken()}`,
          ...(bodyText === null ? {} : {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(bodyText)
          })
        }
      }, (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let payload = {};
          try {
            payload = text ? JSON.parse(text) : {};
          } catch (_error) {
            payload = { ok: false, error: `${method} ${urlPath} returned non-JSON response` };
          }
          if ((response.statusCode || 500) >= 400 || payload.ok === false) {
            const error = new Error(payload.error || `${method} ${urlPath} failed with HTTP ${response.statusCode}`);
            error.status = response.statusCode;
            error.payload = payload;
            reject(error);
            return;
          }
          resolve(payload);
        });
      });
      request.on('timeout', () => request.destroy(new Error('Request timed out.')));
      request.on('error', reject);
      if (bodyText !== null) {
        request.write(bodyText);
      }
      request.end();
    });
  }

  return { requestJson };
}

function waitForBackendReady(url, authToken, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(`${url}/api/status`, {
        timeout: 800,
        headers: { Authorization: `Bearer ${authToken}` }
      }, (response) => {
        response.resume();
        if (response.statusCode === 200) {
          resolve();
          return;
        }
        retry();
      });
      request.on('timeout', () => {
        request.destroy();
        retry();
      });
      request.on('error', retry);
    };
    const retry = () => {
      if (Date.now() >= deadline) {
        reject(new Error('API server did not become ready.'));
        return;
      }
      setTimeout(attempt, 150);
    };
    attempt();
  });
}

// Spawn the Python backend once. Returns a promise that resolves when the
// process spawns successfully and rejects on a spawn 'error' (e.g. ENOENT).
// Fix #1: attach an 'error' handler so an ENOENT (python not on PATH) rejects
// instead of throwing an uncaught exception that crashes the main process
// before the window is created.
function spawnBackendOnce(pythonCommand, args, root, backendStdio, { apiToken, logWrite }) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const child = spawn(pythonCommand, args, {
      cwd: root,
      windowsHide: true,
      stdio: backendStdio,
      // The bearer token authorizes start/stop/recover on an elevated
      // engine; pass it through the environment instead of argv so it never
      // shows up in the Windows process table (WMI CommandLine, EDR
      // telemetry, crash dumps).
      env: { ...process.env, EII_API_TOKEN: apiToken }
    });

    child.once('error', (err) => {
      // Spawn failure (commonly ENOENT). Never let this crash the process.
      console.error(`[api] failed to launch '${pythonCommand}': ${err.message}`);
      if (logWrite) {
        logWrite(`[${new Date().toISOString()}] spawn error (${pythonCommand}): ${err.message}\n`);
      }
      if (!settled) {
        settled = true;
        reject(err);
      }
    });

    // 'spawn' fires once the child process is successfully spawned.
    child.once('spawn', () => {
      if (!settled) {
        settled = true;
        resolve(child);
      }
    });
  });
}

// Bounded auto-restart backoff on unexpected backend exit.
function restartDelayMs(restartCount) {
  return Math.min(8000, 1000 * restartCount);
}

// Fix #6: SIGTERM/child.kill() does not reliably kill the Python process
// tree on Windows; escalate to taskkill /T /F (whole tree) and SIGKILL
// elsewhere so the backend cannot orphan and hold the port.
function forceKillProcessTree(child, { platform = process.platform, spawnFn = spawn } = {}) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  if (platform === 'win32' && child.pid) {
    try {
      spawnFn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
    } catch (_error) {
      child.kill('SIGKILL');
    }
  } else {
    child.kill('SIGKILL');
  }
}

module.exports = {
  createBackendJsonClient,
  findFreePort,
  forceKillProcessTree,
  restartDelayMs,
  spawnBackendOnce,
  waitForBackendReady
};

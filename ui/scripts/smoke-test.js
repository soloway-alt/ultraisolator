const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');

const UI_ROOT = path.resolve(__dirname, '..');
const PROJECT_ROOT = path.resolve(UI_ROOT, '..');
const pythonCommand = process.env.EII_PYTHON || 'python';
const apiToken = process.env.EII_API_TOKEN || 'smoke-local-token';

let apiProcess = null;

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

function requestJson(url, options = {}) {
  const body = options.body || null;
  return new Promise((resolve, reject) => {
    const request = http.request(url, {
      method: options.method || 'GET',
      timeout: 2500,
      headers: {
        ...(options.authorized === false ? {} : { Authorization: `Bearer ${apiToken}` }),
        ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
        ...(options.headers || {})
      }
    }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let payload = {};
        try {
          payload = text ? JSON.parse(text) : {};
        } catch (error) {
          reject(error);
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`${options.method || 'GET'} ${url} returned ${response.statusCode}`));
          return;
        }
        resolve(payload);
      });
    });
    if (body) {
      request.write(body);
    }
    request.on('timeout', () => request.destroy(new Error(`Timed out requesting ${url}`)));
    request.on('error', reject);
    request.end();
  });
}

function requestStatus(url, options = {}) {
  const body = options.body || null;
  return new Promise((resolve, reject) => {
    const request = http.request(url, {
      method: options.method || 'GET',
      timeout: 2500,
      headers: {
        ...(options.authorized === false ? {} : { Authorization: `Bearer ${apiToken}` }),
        ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
        ...(options.headers || {})
      }
    }, (response) => {
      response.resume();
      response.on('end', () => resolve(response.statusCode));
    });
    if (body) {
      request.write(body);
    }
    request.on('timeout', () => request.destroy(new Error(`Timed out requesting ${url}`)));
    request.on('error', reject);
    request.end();
  });
}

function requestText(url, options = {}) {
  return new Promise((resolve, reject) => {
    const request = http.request(url, {
      method: options.method || 'GET',
      timeout: 2500,
      headers: {
        ...(options.authorized === false ? {} : { Authorization: `Bearer ${apiToken}` }),
        ...(options.headers || {})
      }
    }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`${options.method || 'GET'} ${url} returned ${response.statusCode}`));
          return;
        }
        resolve(text);
      });
    });
    request.on('timeout', () => request.destroy(new Error(`Timed out requesting ${url}`)));
    request.on('error', reject);
    request.end();
  });
}

function waitForStatus(baseUrl, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = async () => {
      try {
        resolve(await requestJson(`${baseUrl}/api/status`));
      } catch (error) {
        if (Date.now() >= deadline) {
          reject(error);
          return;
        }
        setTimeout(attempt, 150);
      }
    };
    attempt();
  });
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function stopApi() {
  if (!apiProcess || apiProcess.exitCode !== null) {
    return;
  }
  apiProcess.kill();
}

async function main() {
  const port = await findFreePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const configPath = path.join(os.tmpdir(), `eii-smoke-${process.pid}.json`);
  const distIndex = path.join(UI_ROOT, 'dist', 'index.html');

  assert(fs.existsSync(distIndex), 'dist/index.html is missing. Run npm run build:renderer first.');
  const distHtml = fs.readFileSync(distIndex, 'utf8');
  assert(!distHtml.includes('src="/assets/'), 'dist/index.html uses absolute script assets; Electron file:// loading requires relative paths.');
  assert(!distHtml.includes('href="/assets/'), 'dist/index.html uses absolute style assets; Electron file:// loading requires relative paths.');
  for (const match of distHtml.matchAll(/(?:src|href)="([^"]+)"/g)) {
    const asset = match[1];
    if (asset.startsWith('http') || asset.startsWith('data:') || asset.startsWith('#')) {
      continue;
    }
    assert(fs.existsSync(path.join(path.dirname(distIndex), asset)), `dist asset is missing: ${asset}`);
  }
  const styles = fs.readFileSync(path.join(UI_ROOT, 'src', 'styles.css'), 'utf8');
  assert(styles.includes('overflow-y: auto'), 'The renderer must expose a vertical scroll container for long pages.');
  assert(!styles.includes('unknown'), 'User-facing stylesheet state labels should avoid unknown/debug vocabulary.');
  const electronMain = fs.readFileSync(path.join(UI_ROOT, 'electron-main.js'), 'utf8');
  const appSource = fs.readFileSync(path.join(UI_ROOT, 'src', 'App.jsx'), 'utf8');
  const settingsConstants = fs.readFileSync(path.join(UI_ROOT, 'src', 'constants', 'settings.mjs'), 'utf8');
  assert(electronMain.includes('minimizeToTrayOnStart: false'), 'Electron must open the dashboard on startup by default.');
  assert(settingsConstants.includes('minimizeToTrayOnStart: false'), 'Renderer app settings must default to opening the dashboard on startup.');
  assert(settingsConstants.includes("language: 'en'"), 'Renderer app settings must include a persisted language preference.');
  assert(electronMain.includes('Menu.setApplicationMenu(null)'), 'Electron must remove the default File/Edit/View/Window menu.');
  assert(electronMain.includes('mainWindow.removeMenu()'), 'Electron BrowserWindow must remove the native menu bar.');
  assert(electronMain.includes("loadFile(target.target, { hash: 'dashboard' })"), 'Packaged app must open on Dashboard instead of restoring a stale hash page.');
  assert(appSource.includes('hashchange'), 'Sidebar navigation must support hash changes for robust page switching.');
  assert(appSource.includes("scrollTo({ top: 0, left: 0 })"), 'Page navigation must reset the main scroll container to the top.');

  apiProcess = spawn(pythonCommand, [
    '-m',
    'server',
    '--host',
    '127.0.0.1',
    '--port',
    String(port),
    '--config',
    configPath
  ], {
    cwd: PROJECT_ROOT,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, EII_API_TOKEN: apiToken }
  });

  apiProcess.stderr.on('data', (chunk) => {
    process.stderr.write(`[api] ${chunk}`);
  });

  try {
    const status = await waitForStatus(baseUrl);
    assert(status.running === false, '/api/status should start stopped for smoke test');
    assert(typeof status.admin === 'boolean', '/api/status should expose admin state even when the engine is stopped');
    assert(typeof status.anti_cheat_mode === 'string' && status.anti_cheat_mode.length > 0, '/api/status should expose anti-cheat mode even when the engine is stopped');
    assert(typeof status.background_jailing === 'boolean', '/api/status should expose background jailing config even when the engine is stopped');

    const defaults = await requestJson(`${baseUrl}/api/config/defaults`);
    assert(defaults.defaults && defaults.schema, '/api/config/defaults missing defaults/schema');

    const unauthorizedStatus = await requestStatus(`${baseUrl}/api/status`, { authorized: false });
    assert(unauthorizedStatus === 401, '/api/status should reject missing API token during smoke test');
    const unauthorizedLiveStatus = await requestStatus(`${baseUrl}/api/live?once=1`, { authorized: false });
    assert(unauthorizedLiveStatus === 401, '/api/live should reject missing API token during smoke test');
    const liveFrame = await requestText(`${baseUrl}/api/live?once=1`);
    assert(liveFrame.includes('event: snapshot'), '/api/live?once=1 should emit an SSE snapshot event');
    assert(liveFrame.includes('"running":false'), '/api/live?once=1 should include the stopped runtime snapshot');

    const invalidJsonStatus = await requestStatus(`${baseUrl}/api/config`, {
      method: 'PUT',
      body: '{not json',
      headers: { 'Content-Type': 'application/json' }
    });
    assert(invalidJsonStatus === 400, '/api/config should reject invalid JSON during smoke test');

    const updatedConfig = await requestJson(`${baseUrl}/api/config`, {
      method: 'PUT',
      body: JSON.stringify({ enable_background_jailing: false }),
      headers: { 'Content-Type': 'application/json' }
    });
    assert(updatedConfig.config.enable_background_jailing === false, '/api/config should persist safe smoke setting');

    const topology = await requestJson(`${baseUrl}/api/topology?refresh=1`);
    assert(typeof topology.available === 'boolean', '/api/topology?refresh=1 missing availability flag');
    assert(topology.summary && Array.isArray(topology.cores), '/api/topology?refresh=1 missing topology shape');

    await requestJson(`${baseUrl}/api/stop`, { method: 'POST' });
    console.log(`[smoke] API bridge OK at ${baseUrl}`);
    console.log('[smoke] Renderer build surface OK at dist/index.html');
  } finally {
    stopApi();
  }
}

process.on('SIGINT', () => {
  stopApi();
  process.exit(130);
});
process.on('SIGTERM', () => {
  stopApi();
  process.exit(143);
});

main().catch((error) => {
  stopApi();
  console.error(error);
  process.exit(1);
});

const { app, BrowserWindow, Menu, Tray, nativeImage, ipcMain, globalShortcut } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');
const { pathToFileURL } = require('url');
const {
  appendBackendStartupLog,
  assertProcessElevated,
  backendConfigPath,
  backendManifestPath,
  backendRoot,
  closeBackendLogStream,
  createBackendLogStream,
  isWindowsStartupTaskEnabled,
  preflightPythonRuntime,
  resolvePackagedPythonCommand,
  resolvePythonCommand,
  setWindowsStartupTask,
  verifyBackendResourceIntegrity
} = require('./backend-runtime');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_RENDERER_WIDTH = 1280;
const DEFAULT_RENDERER_HEIGHT = 820;
const SHUTDOWN_TIMEOUT_MS = 5000;
const LIFECYCLE_REQUEST_TIMEOUT_MS = 30000;
const APP_SETTINGS_FILE = 'app-settings.json';
// Canonical app-settings shape shared with the renderer; Electron 42's Node
// supports synchronous require() of a synchronous ES module graph.
const {
  DEFAULT_APP_SETTINGS,
  normalizeAppSettings,
  validateAppSettingsPatch
} = require('./shared/app-settings-schema.mjs');

app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('in-process-gpu');

const singleInstanceLock = app.requestSingleInstanceLock();

let mainWindow = null;
let tray = null;
let backendProcess = null;
let backendUrl = null;
let isQuitting = false;
let lastStatus = { running: false, game_mode: false };
let rendererLoaded = false;
let rendererLoadPromise = null;
let trayStatusTimer = null;
let backendLogStream = null;
let backendStartupError = null;
let backendRestartCount = 0;
let backendRestartTimer = null;
let ipcHandlersRegistered = false;
let liveStreamRequest = null;
let liveStreamReconnectTimer = null;
let liveStreamStopped = true;
let liveStreamBuffer = '';
let appSettingsState = null;
let monitoringDesiredForSession = true;
const MAX_BACKEND_RESTARTS = 4;
const FALLBACK_PYTHON_COMMANDS = ['py', 'python3'];
const backendApiToken = crypto.randomBytes(32).toString('hex');
const MAX_PROXY_BODY_BYTES = 64 * 1024;
const LIVE_RECONNECT_DELAY_MS = 1500;
// Canonical operation table shared with the renderer; Electron 42's Node
// supports synchronous require() of a synchronous ES module graph.
const { BACKEND_OPERATIONS: BACKEND_OPERATION_ALLOWLIST } = require('./shared/backend-operations.mjs');

function appSettingsPath() {
  return path.join(app.getPath('userData'), APP_SETTINGS_FILE);
}

function startupTaskOptions() {
  // Electron's development entry point is ui/package.json, not the repository
  // root used by the Python backend.
  return app.isPackaged ? {} : { arguments: [__dirname] };
}

function readStoredAppSettings() {
  if (appSettingsState) {
    return { ...appSettingsState };
  }
  try {
    const raw = fs.readFileSync(appSettingsPath(), 'utf8');
    const parsed = JSON.parse(raw);
    appSettingsState = normalizeAppSettings({ ...DEFAULT_APP_SETTINGS, ...parsed });
  } catch (_error) {
    appSettingsState = { ...DEFAULT_APP_SETTINGS };
  }
  return { ...appSettingsState };
}

// Reconcile the legacy login item and the scheduled-task startup state with
// the persisted preference. isWindowsStartupTaskEnabled/setWindowsStartupTask
// spawn schtasks.exe SYNCHRONOUSLY on the main thread, so this must run only
// once at bootstrap and when a patch actually changes launchAtWindowsStartup —
// never on every settings read (reads happen on renderer mount and every
// language toggle).
function syncStartupTaskState() {
  const settings = readStoredAppSettings();
  const before = JSON.stringify(settings);
  let legacyEnabled = false;
  let legacyStateKnown = true;
  try {
    legacyEnabled = Boolean(app.getLoginItemSettings().openAtLogin);
  } catch (_error) {
    legacyStateKnown = false;
  }

  let taskEnabled = false;
  try {
    const legacyCleared = disableLegacyLoginItem();
    taskEnabled = isWindowsStartupTaskEnabled();
    if (!legacyCleared && (legacyEnabled || !legacyStateKnown)) {
      if (taskEnabled) {
        taskEnabled = setWindowsStartupTask(false, process.execPath, startupTaskOptions());
      }
    } else if (settings.launchAtWindowsStartup || legacyEnabled) {
      taskEnabled = setWindowsStartupTask(true, process.execPath, startupTaskOptions());
    }
    settings.launchAtWindowsStartup = Boolean(taskEnabled);
  } catch (_error) {
    settings.launchAtWindowsStartup = false;
  }
  appSettingsState = normalizeAppSettings(settings);
  if (JSON.stringify(appSettingsState) !== before) {
    persistAppSettings(appSettingsState);
  }
  return { ...appSettingsState };
}

function disableLegacyLoginItem() {
  try {
    app.setLoginItemSettings({ openAtLogin: false, path: process.execPath });
    return true;
  } catch (_error) {
    return false;
  }
}

function persistAppSettings(settings) {
  const target = appSettingsPath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(settings, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, target);
}

function writeAppSettings(patch) {
  const validatedPatch = validateAppSettingsPatch(patch);
  const current = readStoredAppSettings();
  if (Object.keys(validatedPatch).length === 0) {
    return current;
  }
  const touchesStartupTask = Object.prototype.hasOwnProperty.call(validatedPatch, 'launchAtWindowsStartup');
  if (touchesStartupTask) {
    if (!disableLegacyLoginItem()) {
      throw new Error('Failed to remove the legacy Windows login item.');
    }
    setWindowsStartupTask(Boolean(validatedPatch.launchAtWindowsStartup), process.execPath, startupTaskOptions());
  }
  const settings = normalizeAppSettings({
    ...current,
    ...validatedPatch,
    // Only re-probe the scheduled task (a synchronous schtasks.exe spawn)
    // when this patch actually touched it; a language or toast toggle must
    // not pay for three process spawns.
    launchAtWindowsStartup: touchesStartupTask ? isWindowsStartupTaskEnabled() : current.launchAtWindowsStartup,
    revision: current.revision + 1
  });
  persistAppSettings(settings);
  appSettingsState = settings;
  return { ...settings };
}

function createTrayIcon(state) {
  const iconPath = path.join(__dirname, `assets/tray-${state}.ico`);
  if (fs.existsSync(iconPath)) {
    const image = nativeImage.createFromPath(iconPath);
    if (!image.isEmpty()) {
      return image;
    }
  }

  const colors = {
    idle: '#6F7782',
    game: '#00D4AA',
    error: '#FF4757'
  };
  const color = colors[state] || colors.idle;
  const svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">',
    '<rect width="32" height="32" rx="6" fill="#0A0A0A"/>',
    `<path d="M16 4 26 9v7c0 6.3-4 10.8-10 12-6-1.2-10-5.7-10-12V9l10-5Z" fill="${color}" opacity="0.95"/>`,
    '<path d="M16 8 22 11.1v4.7c0 3.7-2.2 6.4-6 7.4-3.8-1-6-3.7-6-7.4v-4.7L16 8Z" fill="#0A0A0A" opacity="0.88"/>',
    `<path d="M16 11.2 19.8 13.1v3.1c0 2.2-1.3 3.8-3.8 4.6-2.5-.8-3.8-2.4-3.8-4.6v-3.1l3.8-1.9Z" fill="${color}"/>`,
    '</svg>'
  ].join('');
  return nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
}

function setTrayState(state) {
  if (!tray) {
    return;
  }
  tray.setImage(createTrayIcon(state));
  tray.setToolTip(`UltraIsolator - ${state}`);
}

function updateTrayFromStatus(status) {
  lastStatus = {
    running: Boolean(status && status.running),
    game_mode: Boolean(status && status.game_mode)
  };
  if (lastStatus.game_mode) {
    setTrayState('game');
  } else {
    setTrayState('idle');
  }
  updateTrayMenu();
}

function requestBackendJson(urlPath, options = {}) {
  return new Promise((resolve, reject) => {
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
        Authorization: `Bearer ${backendApiToken}`,
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

function postJson(urlPath) {
  return requestBackendJson(urlPath, {
    method: 'POST',
    timeout: LIFECYCLE_REQUEST_TIMEOUT_MS
  });
}

function getJson(urlPath) {
  return requestBackendJson(urlPath, { method: 'GET' });
}

function proxyError(code, message) {
  const error = new Error(`${code}: ${message}`);
  error.code = code;
  return error;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isLoopbackHostname(hostname) {
  return hostname === '127.0.0.1' || hostname === 'localhost' || hostname === '::1' || hostname === '[::1]';
}

function isTrustedRendererUrl(rawUrl) {
  if (!rawUrl) {
    return false;
  }
  let actual;
  try {
    actual = new URL(rawUrl);
  } catch (_error) {
    return false;
  }

  const expected = rendererUrl();
  if (expected.type === 'file') {
    const expectedFileUrl = new URL(pathToFileURL(expected.target).toString());
    return actual.protocol === 'file:' && actual.pathname === expectedFileUrl.pathname;
  }

  if (!app.isPackaged && expected.type === 'url') {
    let expectedUrl;
    try {
      expectedUrl = new URL(expected.target);
    } catch (_error) {
      return false;
    }
    if (!['http:', 'https:'].includes(expectedUrl.protocol) || !isLoopbackHostname(expectedUrl.hostname)) {
      return false;
    }
    return actual.origin === expectedUrl.origin;
  }

  return false;
}

function assertTrustedIpcSender(event) {
  if (!mainWindow || !event || event.sender !== mainWindow.webContents) {
    throw proxyError('forbidden_sender', 'IPC request did not originate from the main dashboard window.');
  }
  if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame) {
    throw proxyError('forbidden_frame', 'IPC backend proxy is restricted to the dashboard main frame.');
  }
  const senderUrl = event.senderFrame.url || event.sender.getURL();
  if (!isTrustedRendererUrl(senderUrl)) {
    throw proxyError('forbidden_renderer_url', 'IPC backend proxy is restricted to the trusted dashboard URL.');
  }
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

function resolveBackendOperation(request = {}) {
  if (!isPlainObject(request)) {
    throw proxyError('invalid_body', 'Backend proxy request must be an object.');
  }
  validateNoExtraRequestKeys(request);
  const definition = BACKEND_OPERATION_ALLOWLIST[request.op];
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

async function proxyBackendRequest(event, request) {
  assertTrustedIpcSender(event);
  const operation = resolveBackendOperation(request);
  if (operation.path === '/api/start') {
    monitoringDesiredForSession = true;
  } else if (operation.path === '/api/stop') {
    monitoringDesiredForSession = false;
  }
  return await requestBackendJson(operation.path, {
    method: operation.method,
    body: operation.body,
    timeout: operation.method === 'POST' ? LIFECYCLE_REQUEST_TIMEOUT_MS : 5000
  });
}

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

function waitForBackendReady(url, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(`${url}/api/status`, {
        timeout: 800,
        headers: { Authorization: `Bearer ${backendApiToken}` }
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
function spawnBackendOnce(pythonCommand, args, root, backendStdio) {
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
      env: { ...process.env, EII_API_TOKEN: backendApiToken }
    });

    child.once('error', (err) => {
      // Spawn failure (commonly ENOENT). Never let this crash the process.
      console.error(`[api] failed to launch '${pythonCommand}': ${err.message}`);
      if (backendLogStream) {
        backendLogStream.write(`[${new Date().toISOString()}] spawn error (${pythonCommand}): ${err.message}\n`);
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

async function launchBackendProcess(port) {
  const root = backendRoot(app, PROJECT_ROOT);
  const args = [
    '-m', 'server',
    '--host', '127.0.0.1',
    '--port', String(port),
    '--config', backendConfigPath(app, PROJECT_ROOT)
  ];
  const backendStdio = app.isPackaged ? ['ignore', 'ignore', 'pipe'] : (
    process.env.EII_BACKEND_LOG_STDIO === '1' ? ['ignore', 'pipe', 'pipe'] : 'ignore'
  );

  if (app.isPackaged) {
    verifyBackendResourceIntegrity({
      backendRoot: root,
      manifestPath: backendManifestPath(__dirname)
    });
    const pythonCommand = resolvePackagedPythonCommand({ app, env: process.env });
    await preflightPythonRuntime(app, PROJECT_ROOT, pythonCommand);
    return await spawnBackendOnce(pythonCommand, args, root, backendStdio);
  }

  // In development, try the configured interpreter first, then fall back to
  // common Windows names ('py', 'python3') if the first spawn fails with ENOENT.
  const candidates = [resolvePythonCommand(), ...FALLBACK_PYTHON_COMMANDS];
  const tried = new Set();
  let lastError = null;
  for (const pythonCommand of candidates) {
    if (tried.has(pythonCommand)) {
      continue;
    }
    tried.add(pythonCommand);
    try {
      await preflightPythonRuntime(app, PROJECT_ROOT, pythonCommand);
      return await spawnBackendOnce(pythonCommand, args, root, backendStdio);
    } catch (error) {
      lastError = error;
      if (error && error.code !== 'ENOENT') {
        // Non-ENOENT errors are not interpreter-name problems; stop trying.
        break;
      }
    }
  }
  throw lastError || new Error('Unable to launch Python backend.');
}

function attachBackendHandlers() {
  backendProcess.on('exit', (code, signal) => {
    backendLogStream = closeBackendLogStream(backendLogStream);
    backendProcess = null;
    if (isQuitting) {
      return;
    }
    // Fix #2: bounded auto-restart with backoff on unexpected backend exit so
    // a crash does not leave a permanently dead app. Guard against loops and
    // against restarting during quit.
    if (backendRestartCount < MAX_BACKEND_RESTARTS) {
      backendRestartCount += 1;
      const delay = Math.min(8000, 1000 * backendRestartCount);
      console.error(`[api] backend exited (code=${code}, signal=${signal}); restart ${backendRestartCount}/${MAX_BACKEND_RESTARTS} in ${delay}ms`);
      setTrayState('error');
      updateTrayMenu();
      if (backendRestartTimer) {
        clearTimeout(backendRestartTimer);
      }
      backendRestartTimer = setTimeout(() => {
        backendRestartTimer = null;
        if (isQuitting) {
          return;
        }
        startBackend().then(async () => {
          startTrayStatusPolling();
          if (monitoringDesiredForSession) {
            await startIsolator();
          } else {
            refreshStatusOnce();
          }
        }).catch((error) => {
          console.error(`[api] backend restart failed: ${error.message}`);
          setTrayState('error');
          updateTrayMenu();
        });
      }, delay);
      if (typeof backendRestartTimer.unref === 'function') {
        backendRestartTimer.unref();
      }
    } else {
      console.error(`[api] backend exited and exhausted ${MAX_BACKEND_RESTARTS} restart attempts; giving up.`);
      setTrayState('error');
      updateTrayMenu();
    }
  });

  if (backendProcess.stderr) {
    if (backendLogStream) {
      backendProcess.stderr.pipe(backendLogStream, { end: false });
    } else {
      backendProcess.stderr.on('data', (chunk) => {
        console.error(`[api] ${chunk.toString().trim()}`);
      });
    }
  }
  if (backendProcess.stdout) {
    backendProcess.stdout.on('data', (chunk) => {
      console.log(`[api] ${chunk.toString().trim()}`);
    });
  }
}

async function startBackend() {
  const port = Number(process.env.EII_API_PORT) || await findFreePort();
  backendUrl = `http://127.0.0.1:${port}`;
  backendLogStream = createBackendLogStream(app);

  // The actual spawn(pythonCommand, args, ...) call lives in spawnBackendOnce
  // so it can be retried across interpreter fallbacks with an error handler.
  backendProcess = await launchBackendProcess(port);
  attachBackendHandlers();

  await waitForBackendReady(backendUrl);
  backendStartupError = null;
  return backendUrl;
}

function rendererUrl() {
  if (!app.isPackaged && process.env.EII_RENDERER_URL) {
    return { type: 'url', target: process.env.EII_RENDERER_URL };
  }
  const startupMessage = backendStartupError
    ? `Startup safety check failed: ${escapeHtml(backendStartupError)}`
    : 'API bridge is running. React dashboard build is not installed yet.';
  if (backendStartupError) {
    const diagnostic = [
      '<!doctype html><html><head><meta charset="utf-8">',
      '<meta name="viewport" content="width=device-width,initial-scale=1">',
      '<title>UltraIsolator</title>',
      '<style>body{margin:0;background:#0A0A0A;color:#E8E8EC;font-family:Inter,Segoe UI,sans-serif}',
      '.shell{display:grid;place-items:center;min-height:100vh;padding:32px}.mark{color:#FF4757;font:700 20px Consolas,monospace;letter-spacing:.08em}',
      '.sub{margin-top:10px;color:#E8E8EC;font-size:13px;max-width:720px;line-height:1.5}</style></head>',
      '<body><main class="shell"><div><div class="mark">ESPORTS ISOLATOR PRO</div>',
      `<div class="sub">${startupMessage}</div></div></main></body></html>`
    ].join('');
    return { type: 'url', target: `data:text/html;charset=utf-8,${encodeURIComponent(diagnostic)}` };
  }
  const distIndex = path.join(__dirname, 'dist', 'index.html');
  if (fs.existsSync(distIndex)) {
    return { type: 'file', target: distIndex };
  }
  const fallback = [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width,initial-scale=1">',
    '<title>UltraIsolator</title>',
    '<style>body{margin:0;background:#0A0A0A;color:#E8E8EC;font-family:Inter,Segoe UI,sans-serif}',
    '.shell{display:grid;place-items:center;min-height:100vh}.mark{color:#00D4AA;font:700 20px Consolas,monospace;letter-spacing:.08em}',
    '.sub{margin-top:10px;color:#AAAAAA;font-size:13px}</style></head>',
    '<body><main class="shell"><div><div class="mark">ESPORTS ISOLATOR PRO</div>',
    `<div class="sub">${startupMessage}</div></div></main></body></html>`
  ].join('');
  return { type: 'url', target: `data:text/html;charset=utf-8,${encodeURIComponent(fallback)}` };
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function rendererFailureUrl(detail) {
  const safeDetail = String(detail || 'Renderer failed to mount. Rebuild the dashboard and reopen the app.')
    .replace(/[<>&]/g, (char) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[char]));
  const fallback = [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width,initial-scale=1">',
    '<title>UltraIsolator</title>',
    '<style>body{margin:0;background:#0A0A0A;color:#E8E8EC;font-family:Inter,Segoe UI,sans-serif}',
    '.shell{display:grid;place-items:center;min-height:100vh}.mark{color:#FF4757;font:700 20px Consolas,monospace;letter-spacing:.08em}',
    '.sub{margin-top:10px;color:#AAAAAA;font-size:13px;max-width:560px;line-height:1.5}</style></head>',
    `<body><main class="shell"><div><div class="mark">RENDERER LOAD FAILED</div><div class="sub">${safeDetail}</div></div></main></body></html>`
  ].join('');
  return `data:text/html;charset=utf-8,${encodeURIComponent(fallback)}`;
}

function waitForRendererMount(timeoutMs = 5000) {
  if (!mainWindow) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    const check = () => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        resolve(false);
        return;
      }
      mainWindow.webContents.executeJavaScript(
        'Boolean(document.querySelector("#root") && document.querySelector("#root").children.length)',
        true
      ).then((mounted) => {
        if (mounted || Date.now() >= deadline) {
          resolve(Boolean(mounted));
          return;
        }
        setTimeout(check, 100);
      }).catch(() => resolve(false));
    };
    check();
  });
}

function ensureRendererLoaded() {
  if (!mainWindow || rendererLoaded) {
    return Promise.resolve();
  }
  if (rendererLoadPromise) {
    return rendererLoadPromise;
  }
  const target = rendererUrl();
  rendererLoadPromise = (target.type === 'file'
    ? mainWindow.loadFile(target.target, { hash: 'dashboard' })
    : mainWindow.loadURL(target.target))
    .then(async () => {
      if (backendStartupError) {
        rendererLoaded = true;
        return;
      }
      const mounted = await waitForRendererMount();
      if (!mounted) {
        await mainWindow.loadURL(rendererFailureUrl('React did not mount from the packaged renderer build. Run npm --prefix ui run build:renderer and check ui/dist/index.html asset paths.'));
      }
      rendererLoaded = true;
    })
    .finally(() => {
      rendererLoadPromise = null;
    });
  return rendererLoadPromise;
}

async function refreshStatusOnce() {
  try {
    const status = await getJson('/api/status');
    updateTrayFromStatus(status);
    return status;
  } catch (_error) {
    setTrayState('error');
    updateTrayMenu();
    return null;
  }
}

function startTrayStatusPolling() {
  if (trayStatusTimer) {
    return;
  }
  trayStatusTimer = setInterval(refreshStatusOnce, 15000);
  if (typeof trayStatusTimer.unref === 'function') {
    trayStatusTimer.unref();
  }
}

function stopTrayStatusPolling() {
  if (!trayStatusTimer) {
    return;
  }
  clearInterval(trayStatusTimer);
  trayStatusTimer = null;
}

function sendLiveSnapshotEvent(payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send('live:event', payload);
}

function parseSseFrame(frame) {
  const lines = String(frame).split(/\r?\n/);
  const data = [];
  let eventName = 'message';
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).trimStart());
    }
  }
  return { eventName, data: data.join('\n') };
}

function scheduleLiveStreamReconnect(message) {
  if (liveStreamStopped) {
    return;
  }
  if (liveStreamReconnectTimer) {
    clearTimeout(liveStreamReconnectTimer);
  }
  sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'error', error: message } });
  liveStreamReconnectTimer = setTimeout(() => {
    liveStreamReconnectTimer = null;
    openLiveStream();
  }, LIVE_RECONNECT_DELAY_MS);
  if (typeof liveStreamReconnectTimer.unref === 'function') {
    liveStreamReconnectTimer.unref();
  }
}

function handleLiveSseFrame(frame) {
  const { eventName, data } = parseSseFrame(frame);
  if (eventName === 'snapshot') {
    try {
      const snapshot = JSON.parse(data);
      updateTrayFromStatus(snapshot.status);
    } catch (_error) {
      sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'error', error: 'malformed live frame' } });
      return;
    }
  }
  sendLiveSnapshotEvent({ eventName, data });
}

function stopLiveStream(options = {}) {
  liveStreamStopped = true;
  liveStreamBuffer = '';
  if (liveStreamReconnectTimer) {
    clearTimeout(liveStreamReconnectTimer);
    liveStreamReconnectTimer = null;
  }
  if (liveStreamRequest) {
    const request = liveStreamRequest;
    liveStreamRequest = null;
    request.destroy();
  }
  if (options.notify !== false) {
    sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'paused', error: null } });
  }
}

function openLiveStream() {
  if (liveStreamStopped) {
    return;
  }
  if (!backendUrl) {
    scheduleLiveStreamReconnect('Backend is not ready.');
    return;
  }
  if (liveStreamRequest) {
    return;
  }
  const url = new URL('/api/live', backendUrl);
  sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'connecting', error: null } });
  const request = http.get({
    hostname: url.hostname,
    port: url.port,
    path: url.pathname,
    timeout: 0,
    headers: {
      Authorization: `Bearer ${backendApiToken}`
    }
  }, (response) => {
    if (response.statusCode !== 200) {
      response.resume();
      liveStreamRequest = null;
      const message = `live stream failed with HTTP ${response.statusCode}`;
      if (response.statusCode === 401 || response.statusCode === 403) {
        sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'error', error: message } });
        return;
      }
      scheduleLiveStreamReconnect(message);
      return;
    }

    sendLiveSnapshotEvent({ eventName: 'state', data: { connectionState: 'connected', error: null } });
    response.setEncoding('utf8');
    response.on('data', (chunk) => {
      liveStreamBuffer += chunk;
      const frames = liveStreamBuffer.split(/\r?\n\r?\n/);
      liveStreamBuffer = frames.pop() || '';
      for (const frame of frames) {
        handleLiveSseFrame(frame);
      }
    });
    response.on('end', () => {
      liveStreamRequest = null;
      liveStreamBuffer = '';
      scheduleLiveStreamReconnect('live stream disconnected');
    });
  });
  liveStreamRequest = request;
  request.on('error', (error) => {
    liveStreamRequest = null;
    liveStreamBuffer = '';
    if (!liveStreamStopped) {
      scheduleLiveStreamReconnect(error instanceof Error ? error.message : 'live stream unavailable');
    }
  });
}

function startLiveStream(event) {
  assertTrustedIpcSender(event);
  if (liveStreamRequest && !liveStreamStopped) {
    return { ok: true };
  }
  liveStreamStopped = false;
  liveStreamBuffer = '';
  openLiveStream();
  return { ok: true };
}

function stopLiveStreamForRenderer(event) {
  assertTrustedIpcSender(event);
  stopLiveStream();
  return { ok: true };
}

async function showMainWindow() {
  if (!mainWindow) {
    return;
  }
  try {
    await ensureRendererLoaded();
  } catch (_error) {
    setTrayState('error');
    return;
  }
  // Fix #7: a minimized window won't reappear from show()+focus() alone;
  // restore it (and clear skip-taskbar) before focusing.
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.setSkipTaskbar(false);
  mainWindow.show();
  mainWindow.focus();
  mainWindow.webContents.send('tray:show-window', {});
  refreshStatusOnce();
}

function hideMainWindow() {
  if (mainWindow) {
    mainWindow.hide();
  }
}

async function startIsolator() {
  monitoringDesiredForSession = true;
  try {
    const result = await postJson('/api/start');
    updateTrayFromStatus(result.status || { running: result.ok, game_mode: false });
  } catch (_error) {
    setTrayState('error');
  }
}

async function stopIsolator() {
  monitoringDesiredForSession = false;
  try {
    const result = await postJson('/api/stop');
    updateTrayFromStatus(result.status || { running: false, game_mode: false });
  } catch (_error) {
    setTrayState('error');
  }
}

function updateTrayMenu() {
  if (!tray) {
    return;
  }
  const lifecycleLabel = lastStatus.running ? 'Stop Isolator' : 'Start Isolator';
  const lifecycleClick = lastStatus.running ? stopIsolator : startIsolator;
  const menu = Menu.buildFromTemplate([
    { label: 'Open Dashboard', click: showMainWindow },
    { type: 'separator' },
    { label: lifecycleLabel, click: lifecycleClick },
    { type: 'separator' },
    { label: 'Exit', click: quitApplication }
  ]);
  tray.setContextMenu(menu);
}

function createTray() {
  tray = new Tray(createTrayIcon('idle'));
  tray.on('double-click', showMainWindow);
  tray.on('click', showMainWindow);
  updateTrayMenu();
}

function createWindow() {
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: DEFAULT_RENDERER_WIDTH,
    height: DEFAULT_RENDERER_HEIGHT,
    minWidth: 980,
    minHeight: 640,
    show: false,
    title: 'UltraIsolator',
    icon: path.join(__dirname, 'assets/icon.ico'),
    backgroundColor: '#0A0A0A',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'electron-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  mainWindow.removeMenu();
  mainWindow.setMenuBarVisibility(false);

  // The dashboard never needs media/geolocation/notification/etc. browser
  // permissions; deny everything so a compromised renderer cannot request
  // them either.
  mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    stopLiveStream({ notify: false });
    if (!isQuitting && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.loadURL(rendererFailureUrl(`Renderer process exited: ${details.reason || 'unknown reason'}.`)).catch(() => {});
    }
  });
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    const target = rendererUrl();
    if (target.type === 'file') {
      event.preventDefault();
      return;
    }
    if (targetUrl !== target.target) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
}

// Fix #3: forcibly kill a spawned backend (used when bootstrap fails after a
// spawn but before the API is ready) so no orphaned Python process is left
// holding the port. Detaches handlers first so it does not trigger auto-restart.
function killBackendProcess() {
  stopLiveStream({ notify: false });
  if (backendRestartTimer) {
    clearTimeout(backendRestartTimer);
    backendRestartTimer = null;
  }
  const child = backendProcess;
  backendProcess = null;
  backendLogStream = closeBackendLogStream(backendLogStream);
  if (!child) {
    return;
  }
  try {
    child.removeAllListeners('exit');
    if (child.exitCode === null && child.signalCode === null) {
      if (process.platform === 'win32' && child.pid) {
        try {
          spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
        } catch (_error) {
          child.kill();
        }
      } else {
        child.kill('SIGKILL');
      }
    }
  } catch (error) {
    console.error(`[api] failed to kill backend: ${error.message}`);
  }
}

async function gracefulShutdownBackend() {
  try {
    await postJson('/api/stop');
  } catch (_error) {
    // Best effort: the backend may have exited before Electron shutdown.
  }
  if (!backendProcess) {
    return;
  }
  const child = backendProcess;
  // Don't let the unexpected-exit auto-restart fire during a deliberate quit.
  child.removeAllListeners('exit');
  if (backendRestartTimer) {
    clearTimeout(backendRestartTimer);
    backendRestartTimer = null;
  }
  await new Promise((resolve) => {
    const timer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        // Fix #6: SIGTERM/child.kill() does not reliably kill the Python
        // process tree on Windows; escalate to taskkill /T /F (whole tree) and
        // SIGKILL elsewhere so the backend cannot orphan and hold the port.
        if (process.platform === 'win32' && child.pid) {
          try {
            spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
          } catch (_error) {
            child.kill('SIGKILL');
          }
        } else {
          child.kill('SIGKILL');
        }
      }
      resolve();
    }, SHUTDOWN_TIMEOUT_MS);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill();
  });
}

async function quitApplication() {
  if (isQuitting) {
    return;
  }
  isQuitting = true;
  stopLiveStream({ notify: false });
  stopTrayStatusPolling();
  await gracefulShutdownBackend();
  app.quit();
}

function requestGracefulQuit() {
  quitApplication().catch((error) => {
    console.error(error);
    app.exit(1);
  });
}

function getAppSettingsForRenderer(event) {
  assertTrustedIpcSender(event);
  // Pure cached read: the startup-task reconciliation ran at bootstrap and
  // runs again only when a patch changes launchAtWindowsStartup.
  return readStoredAppSettings();
}

function updateAppSettingsForRenderer(event, patch) {
  assertTrustedIpcSender(event);
  return writeAppSettings(patch);
}

function registerIpcHandlers() {
  if (ipcHandlersRegistered) {
    return;
  }
  ipcHandlersRegistered = true;
  // Every channel goes through the sender check so a new handler cannot be
  // added without it. Handlers that already assert internally keep doing so;
  // the double check is cheap and fails identically.
  const guarded = (handler) => (event, ...args) => {
    assertTrustedIpcSender(event);
    return handler(event, ...args);
  };
  ipcMain.handle('backend:request', guarded(proxyBackendRequest));
  ipcMain.handle('live:start', guarded(startLiveStream));
  ipcMain.handle('live:stop', guarded(stopLiveStreamForRenderer));
  ipcMain.handle('window:minimize', guarded(() => {
    if (mainWindow) {
      mainWindow.minimize();
    }
  }));
  ipcMain.handle('window:close-to-tray', guarded(() => hideMainWindow()));
  ipcMain.handle('window:show', guarded(() => showMainWindow()));
  ipcMain.handle('app-settings:get', guarded(getAppSettingsForRenderer));
  ipcMain.handle('app-settings:update', guarded(updateAppSettingsForRenderer));
  ipcMain.handle('tray:status', guarded((_event, status) => {
    // The tray menu offers Start or Stop based on this payload, so accept
    // only the two known boolean fields from the renderer.
    if (!isPlainObject(status)) {
      throw proxyError('invalid_body', 'tray:status payload must be an object.');
    }
    updateTrayFromStatus({
      running: Boolean(status.running),
      game_mode: Boolean(status.game_mode)
    });
    return true;
  }));
}

// Fix #3: when bootstrap fails (e.g. waitForBackendReady times out) we must not
// leave an orphaned Python process and a dead tray-only app. Kill any spawned
// backend and show a tray menu that offers a working Retry and Quit.
function setTrayErrorMenu() {
  if (!tray) {
    return;
  }
  setTrayState('error');
  const menu = Menu.buildFromTemplate([
    { label: 'Backend failed to start', enabled: false },
    { type: 'separator' },
    { label: 'Retry', click: retryBootstrap },
    { label: 'Exit', click: quitApplication }
  ]);
  tray.setContextMenu(menu);
}

function retryBootstrap() {
  // Reset restart budget for a manual retry and re-run bootstrap.
  backendRestartCount = 0;
  killBackendProcess();
  bootstrap().catch(handleBootstrapFailure);
}

function handleBootstrapFailure(error) {
  backendStartupError = error instanceof Error ? error.message : String(error);
  console.error(`[bootstrap] startup failed: ${backendStartupError}`);
  appendBackendStartupLog(app, backendStartupError);
  // Ensure no orphaned backend is left holding the port.
  killBackendProcess();
  stopTrayStatusPolling();
  setTrayErrorMenu();
  if (!mainWindow) {
    createWindow();
  }
  showMainWindow().catch(() => {});
}

async function bootstrap() {
  app.setAppUserModelId('com.esportsisolator.pro');
  const appSettings = syncStartupTaskState();
  if (!tray) {
    createTray();
  }
  registerIpcHandlers();
  try {
    await startBackend();
  } catch (error) {
    // startBackend failed to spawn (ENOENT) or never became ready. Clean up the
    // orphan and surface a recoverable error state instead of crashing.
    handleBootstrapFailure(error);
    return;
  }
  startTrayStatusPolling();
  if (!mainWindow) {
    createWindow();
  }
  updateTrayMenu();
  await startIsolator();
  if (appSettings.minimizeToTrayOnStart) {
    await ensureRendererLoaded();
  } else {
    await showMainWindow();
  }
  globalShortcut.register('CommandOrControl+Q', quitApplication);
}

if (!singleInstanceLock) {
  app.quit();
} else {
  let elevationError = null;
  try {
    assertProcessElevated();
  } catch (error) {
    elevationError = error;
  }
  if (elevationError) {
    console.error(`[bootstrap] ${elevationError.code || 'administrator_required'}`);
    app.exit(elevationError.exitCode || 5);
  } else {
    app.on('second-instance', () => {
      showMainWindow();
    });

    app.whenReady().then(bootstrap).catch(handleBootstrapFailure);

    app.on('activate', showMainWindow);

    app.on('before-quit', (event) => {
      if (!isQuitting) {
        event.preventDefault();
        quitApplication();
      }
    });

    app.on('will-quit', () => {
      globalShortcut.unregisterAll();
    });

    app.on('window-all-closed', (event) => {
      event.preventDefault();
    });

    process.on('SIGINT', () => {
      requestGracefulQuit();
    });

    process.on('SIGTERM', () => {
      requestGracefulQuit();
    });
  }
}

const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const BACKEND_MANIFEST_FILE = 'backend-manifest.json';
const PACKAGED_PYTHON_DEV_OVERRIDE = 'EII_ALLOW_UNTRUSTED_PACKAGED_PYTHON';
const DYNAMIC_BACKEND_STATE_FILES = new Set([
  'config.json',
  'ifeo_backup.json',
  'jail_state.json',
  'recovery_state.json'
]);
const IGNORED_BACKEND_FILE_EXTENSIONS = new Set(['.log', '.tmp', '.pyc', '.pyo']);
const IGNORED_BACKEND_DIRECTORIES = new Set(['__pycache__', '.pytest_cache']);
const WINDOWS_STARTUP_TASK_NAME = '\\UltraIsolator\\LaunchAtLogon';

function isProcessElevated(options = {}) {
  const platform = options.platform || process.platform;
  const run = options.spawnSync || spawnSync;
  if (platform !== 'win32') {
    return false;
  }
  const script = [
    '$identity = [Security.Principal.WindowsIdentity]::GetCurrent()',
    '$principal = New-Object Security.Principal.WindowsPrincipal($identity)',
    'if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Output ELEVATED }'
  ].join('; ');
  const result = run('powershell.exe', [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-Command',
    script
  ], {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 5000
  });
  return !result.error && result.status === 0 && String(result.stdout || '').trim() === 'ELEVATED';
}

function assertProcessElevated(options = {}) {
  if (isProcessElevated(options)) {
    return true;
  }
  const error = new Error('Administrator rights are required.');
  error.code = 'administrator_required';
  error.exitCode = 5;
  throw error;
}

function runTaskScheduler(args, options = {}) {
  const run = options.spawnSync || spawnSync;
  return run('schtasks.exe', args, {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 10000
  });
}

function isWindowsStartupTaskEnabled(options = {}) {
  const platform = options.platform || process.platform;
  if (platform !== 'win32') {
    return false;
  }
  const result = runTaskScheduler(['/Query', '/TN', WINDOWS_STARTUP_TASK_NAME], options);
  return !result.error && result.status === 0;
}

function setWindowsStartupTask(enabled, executablePath, options = {}) {
  const platform = options.platform || process.platform;
  if (platform !== 'win32') {
    throw new Error('Windows startup tasks are only supported on Windows.');
  }
  if (!enabled) {
    if (!isWindowsStartupTaskEnabled(options)) {
      return false;
    }
    const removed = runTaskScheduler(['/Delete', '/TN', WINDOWS_STARTUP_TASK_NAME, '/F'], options);
    if (removed.error || removed.status !== 0) {
      throw new Error(`Failed to remove startup task: ${String(removed.stderr || removed.error || '').trim()}`);
    }
    return false;
  }
  if (!path.isAbsolute(executablePath) || executablePath.includes('"')) {
    throw new Error('Startup executable path is invalid.');
  }
  const launchArguments = Array.isArray(options.arguments) ? options.arguments.map(String) : [];
  if (launchArguments.some((argument) => argument.includes('"') || /[\r\n]/.test(argument))) {
    throw new Error('Startup launch arguments are invalid.');
  }
  const taskCommand = [`"${executablePath}"`, ...launchArguments.map((argument) => `"${argument}"`)].join(' ');
  const created = runTaskScheduler([
    '/Create',
    '/TN', WINDOWS_STARTUP_TASK_NAME,
    '/TR', taskCommand,
    '/SC', 'ONLOGON',
    '/RL', 'HIGHEST',
    '/IT',
    '/F'
  ], options);
  if (created.error || created.status !== 0) {
    throw new Error(`Failed to create startup task: ${String(created.stderr || created.error || '').trim()}`);
  }
  return true;
}

function backendRoot(app, projectRoot) {
  return app.isPackaged ? path.join(process.resourcesPath, 'backend') : projectRoot;
}

function backendManifestPath(appDir = __dirname) {
  // In packaged builds this lives in the ASAR/app bundle, not under the mutable
  // extraResources backend tree it verifies.
  return path.join(appDir, BACKEND_MANIFEST_FILE);
}

function backendConfigPath(app, projectRoot) {
  const root = backendRoot(app, projectRoot);
  if (app.isPackaged) {
    // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal -- Electron userData path is app-controlled; filename is fixed.
    return path.join(app.getPath('userData'), 'config.json');
  }
  // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal -- projectRoot is the application root; filename is fixed.
  return path.join(root, 'config.json');
}

function resolvePythonCommand(env = process.env) {
  return env.EII_PYTHON || 'python';
}

function safeRealpathSync(target) {
  try {
    const realpath = fs.realpathSync.native || fs.realpathSync;
    return realpath(target);
  } catch (_error) {
    return path.resolve(target);
  }
}

function normalizeComparablePath(target) {
  return path.resolve(target).replace(/[\\/]+$/, '').toLowerCase();
}

function isPathUnderTrustedRoot(target, trustedRoots = []) {
  const normalizedTarget = normalizeComparablePath(target);
  return trustedRoots.some((root) => {
    if (!root) {
      return false;
    }
    const normalizedRoot = normalizeComparablePath(root);
    return normalizedTarget === normalizedRoot || normalizedTarget.startsWith(`${normalizedRoot}${path.sep}`);
  });
}

function defaultTrustedPythonRoots() {
  const roots = [];
  if (process.resourcesPath) {
    roots.push(path.join(process.resourcesPath, 'python'));
  }
  if (process.platform === 'win32') {
    const programFiles = process.env.ProgramFiles || 'C:\\Program Files';
    roots.push(path.join(programFiles, 'Esports Isolator PRO', 'python'));
  }
  return roots;
}

function aclGrantsStandardUserWrite(aclText) {
  const riskyPrincipals = [
    'everyone',
    'authenticated users',
    'builtin\\users',
    'nt authority\\authenticated users',
    'users',
    's-1-1-0',
    's-1-5-11',
    's-1-5-32-545'
  ];
  return String(aclText || '').split(/\r?\n/).some((line) => {
    const lower = line.toLowerCase();
    if (lower.includes('(deny)') || /\bdeny\b/.test(lower)) {
      return false;
    }
    const grantsWrite = /\(([^)]*\b(f|m|w|wd|ad|dc|wo)\b[^)]*)\)/i.test(line) ||
      /\b(fullcontrol|modify|write|writedata|createfiles|appenddata|delete|takeownership|changepermissions)\b/i.test(line);
    return grantsWrite && riskyPrincipals.some((principal) => lower.includes(principal));
  });
}

function readWindowsAclText(target) {
  const psScript = [
    "$ErrorActionPreference = 'Stop'",
    "$acl = Get-Acl -LiteralPath $args[0]",
    "foreach ($ace in $acl.Access) {",
    "  try { $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }",
    "  catch { $sid = $ace.IdentityReference.Value }",
    "  Write-Output (\"{0} {1} {2}\" -f $sid, $ace.AccessControlType, $ace.FileSystemRights)",
    "}"
  ].join('; ');
  const psResult = spawnSync('powershell', [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-Command',
    psScript,
    target
  ], {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
  if (!psResult.error && psResult.status === 0) {
    return `${psResult.stdout}\n${psResult.stderr}`;
  }

  const icaclsResult = spawnSync('icacls', [target], {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
  if (icaclsResult.error || icaclsResult.status !== 0) {
    return null;
  }
  return `${icaclsResult.stdout}\n${icaclsResult.stderr}`;
}

function isPathWritableByStandardUsers(target) {
  if (process.platform === 'win32') {
    const aclText = readWindowsAclText(target);
    if (aclText === null) {
      return true;
    }
    return aclGrantsStandardUserWrite(aclText);
  }

  try {
    const stat = fs.statSync(target);
    return Boolean(stat.mode & 0o022);
  } catch (_error) {
    return true;
  }
}

function assertNotWritableByStandardUsers(target, writableCheck, description = 'Packaged runtime path') {
  const targets = [target];
  try {
    const stat = fs.statSync(target);
    if (stat.isFile()) {
      targets.push(path.dirname(target));
    }
  } catch (_error) {
    targets.push(path.dirname(target));
  }

  for (const candidate of [...new Set(targets)]) {
    if (writableCheck(candidate)) {
      throw new Error(`${description} is writable by standard users: ${candidate}`);
    }
  }
}

function manifestAclPath(manifestPath) {
  const marker = `${path.sep}app.asar`;
  const markerIndex = manifestPath.toLowerCase().indexOf(marker);
  if (markerIndex === -1) {
    return manifestPath;
  }
  return manifestPath.slice(0, markerIndex + marker.length);
}

function validatePythonProvenance(options) {
  const {
    command,
    trustedRoots = defaultTrustedPythonRoots(),
    isPathWritableByStandardUsers: writableCheck = isPathWritableByStandardUsers
  } = options || {};

  if (!command || !path.isAbsolute(command)) {
    throw new Error('Packaged Python runtime must be an absolute trusted path.');
  }

  const realCommand = safeRealpathSync(command);
  if (!isPathUnderTrustedRoot(realCommand, trustedRoots)) {
    throw new Error(
      `Packaged EII_PYTHON is outside trusted Python roots; set ${PACKAGED_PYTHON_DEV_OVERRIDE}=1 only for non-production developer override diagnostics.`
    );
  }
  if (!fs.existsSync(realCommand)) {
    throw new Error(`Packaged Python runtime is missing: ${command}`);
  }
  const commandStat = fs.statSync(realCommand);
  if (!commandStat.isFile()) {
    throw new Error(`Packaged Python runtime must be an executable file: ${command}`);
  }

  assertNotWritableByStandardUsers(realCommand, writableCheck);
  return realCommand;
}

function isProductionPackagedRuntime(app, env, explicitValue) {
  if (typeof explicitValue === 'boolean') {
    return explicitValue;
  }
  return Boolean(app && app.isPackaged);
}

function resolvePackagedPythonCommand(options = {}) {
  const {
    app = { isPackaged: true },
    env = process.env,
    isProduction,
    trustedRoots = defaultTrustedPythonRoots(),
    isPathWritableByStandardUsers: writableCheck = isPathWritableByStandardUsers,
    bundledPythonPath = process.resourcesPath ? path.join(process.resourcesPath, 'python', 'python.exe') : ''
  } = options;
  const configuredPython = env.EII_PYTHON || '';
  const production = isProductionPackagedRuntime(app, env, isProduction);
  const devOverrideAllowed = env[PACKAGED_PYTHON_DEV_OVERRIDE] === '1' && !production;

  if (configuredPython) {
    if (devOverrideAllowed) {
      if (!path.isAbsolute(configuredPython)) {
        throw new Error('Packaged Python developer override must be an absolute path.');
      }
      return safeRealpathSync(configuredPython);
    }
    if (env[PACKAGED_PYTHON_DEV_OVERRIDE] === '1' && production) {
      throw new Error('Packaged Python developer override is disabled in production builds.');
    }
    return validatePythonProvenance({
      command: configuredPython,
      trustedRoots,
      isPathWritableByStandardUsers: writableCheck
    });
  }

  if (!bundledPythonPath) {
    throw new Error('Packaged builds require a bundled trusted Python runtime.');
  }
  return validatePythonProvenance({
    command: bundledPythonPath,
    trustedRoots,
    isPathWritableByStandardUsers: writableCheck
  });
}

function backendLogPath(app) {
  // nosemgrep: javascript.lang.security.audit.path-traversal.path-join-resolve-traversal.path-join-resolve-traversal -- Electron userData path is app-controlled; filename is fixed.
  return path.join(app.getPath('userData'), 'backend.log');
}

function createBackendLogStream(app) {
  if (!app.isPackaged) {
    return null;
  }
  try {
    const target = backendLogPath(app);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const stream = fs.createWriteStream(target, { flags: 'a' });
    stream.write(`[${new Date().toISOString()}] starting backend\n`);
    return stream;
  } catch (error) {
    console.error(error);
    return null;
  }
}

function appendBackendStartupLog(app, message) {
  if (!app.isPackaged) {
    console.error(message);
    return;
  }
  try {
    const target = backendLogPath(app);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.appendFileSync(target, `[${new Date().toISOString()}] ${message}\n`, 'utf8');
  } catch (error) {
    console.error(error);
  }
}

function closeBackendLogStream(stream) {
  if (!stream) {
    return null;
  }
  stream.end(`[${new Date().toISOString()}] backend exited\n`);
  return null;
}

function runPythonProbe(app, projectRoot, pythonCommand, args) {
  return new Promise((resolve, reject) => {
    // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process -- documented EII_PYTHON runtime selector; spawn uses fixed args without a shell.
    const child = spawn(pythonCommand, args, {
      cwd: backendRoot(app, projectRoot),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    const stdout = [];
    const stderr = [];
    child.stdout.on('data', (chunk) => stdout.push(chunk));
    child.stderr.on('data', (chunk) => stderr.push(chunk));
    child.on('error', reject);
    child.on('exit', (code) => {
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString('utf8').trim(),
        stderr: Buffer.concat(stderr).toString('utf8').trim()
      });
    });
  });
}

async function preflightPythonRuntime(app, projectRoot, pythonCommand) {
  const version = await runPythonProbe(app, projectRoot, pythonCommand, ['--version']);
  const versionText = `${version.stdout} ${version.stderr}`.trim();
  const match = versionText.match(/Python\s+(\d+)\.(\d+)/);
  if (!match || Number(match[1]) < 3 || (Number(match[1]) === 3 && Number(match[2]) < 12)) {
    throw new Error(`Python 3.12 or newer is required. Found: ${versionText || 'unavailable'}. Set EII_PYTHON to a valid interpreter.`);
  }

  const psutil = await runPythonProbe(app, projectRoot, pythonCommand, ['-c', 'import psutil; print(psutil.__version__)']);
  if (psutil.code !== 0) {
    throw new Error(`Python dependency psutil is missing for ${pythonCommand}. Run: python -m pip install -r requirements.txt`);
  }
}

function toManifestPath(relativePath) {
  return relativePath.split(path.sep).join('/');
}

function isIgnoredBackendPath(relativePath) {
  const normalized = toManifestPath(relativePath);
  const parts = normalized.split('/');
  const basename = parts[parts.length - 1];
  const extension = path.extname(basename).toLowerCase();
  return parts.some((part) => IGNORED_BACKEND_DIRECTORIES.has(part)) ||
    DYNAMIC_BACKEND_STATE_FILES.has(basename) ||
    IGNORED_BACKEND_FILE_EXTENSIONS.has(extension) ||
    basename.endsWith('.tmp');
}

function walkBackendFiles(root, current = root, output = []) {
  for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
    const fullPath = path.join(current, entry.name);
    const relativePath = toManifestPath(path.relative(root, fullPath));
    if (isIgnoredBackendPath(relativePath)) {
      continue;
    }
    if (entry.isSymbolicLink()) {
      throw new Error(`Backend resource file is not listed in integrity manifest: ${relativePath}`);
    } else if (entry.isDirectory()) {
      walkBackendFiles(root, fullPath, output);
    } else if (entry.isFile()) {
      output.push(relativePath);
    } else {
      throw new Error(`Backend resource file is not listed in integrity manifest: ${relativePath}`);
    }
  }
  return output;
}

function readBackendManifest(manifestPath) {
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Backend resource manifest is missing: ${manifestPath}`);
  }
  return validateBackendManifest(JSON.parse(fs.readFileSync(manifestPath, 'utf8')));
}

function validateBackendManifest(parsed) {
  if (!parsed || parsed.version !== 1 || parsed.algorithm !== 'sha256' || !parsed.files || typeof parsed.files !== 'object') {
    throw new Error('Backend resource manifest is invalid.');
  }
  return parsed;
}

function assertManifestPathIsTrusted(backendRootPath, manifestPath) {
  const relative = path.relative(backendRootPath, manifestPath);
  if (relative && !relative.startsWith('..') && !path.isAbsolute(relative)) {
    throw new Error('Backend resource manifest must be stored in the trusted app bundle, not under mutable resources/backend.');
  }
}

function validateManifestEntry(relativePath) {
  if (path.isAbsolute(relativePath) || relativePath.includes('\\')) {
    throw new Error(`Backend resource manifest path is invalid: ${relativePath}`);
  }
  const normalized = path.posix.normalize(relativePath);
  if (normalized.startsWith('../') || normalized === '..') {
    throw new Error(`Backend resource manifest path escapes backend root: ${relativePath}`);
  }
  return normalized;
}

function sha256File(filePath) {
  // Normalize CRLF to LF before hashing so integrity verification does not
  // depend on how git materialized line endings when the backend resources
  // were checked out. Must stay byte-for-byte identical to hashFile in
  // ui/scripts/generate-backend-manifest.js.
  const raw = fs.readFileSync(filePath);
  const normalized = raw.includes(0x0d)
    ? Buffer.from(raw.toString('latin1').replace(/\r\n/g, '\n'), 'latin1')
    : raw;
  return crypto.createHash('sha256').update(normalized).digest('hex');
}

function verifyBackendResourceIntegrity(options = {}) {
  const {
    backendRoot: backendRootPath,
    manifestPath = backendManifestPath(),
    manifest,
    isPathWritableByStandardUsers: writableCheck = isPathWritableByStandardUsers
  } = options;

  if (!backendRootPath || !fs.existsSync(backendRootPath)) {
    throw new Error(`Backend resource root is missing: ${backendRootPath || 'unavailable'}`);
  }
  assertManifestPathIsTrusted(backendRootPath, manifestPath);
  assertNotWritableByStandardUsers(manifestAclPath(manifestPath), writableCheck, 'Backend resource manifest path');
  assertNotWritableByStandardUsers(backendRootPath, writableCheck);

  const parsedManifest = manifest ? validateBackendManifest(manifest) : readBackendManifest(manifestPath);
  const manifestFiles = new Map();
  for (const [relativePath, expected] of Object.entries(parsedManifest.files)) {
    const normalized = validateManifestEntry(relativePath);
    if (typeof expected !== 'string' || !expected.startsWith('sha256-')) {
      throw new Error(`Backend resource manifest hash is invalid for ${normalized}`);
    }
    manifestFiles.set(normalized, expected.slice('sha256-'.length));
  }

  for (const [relativePath, expectedHash] of manifestFiles.entries()) {
    const fullPath = path.join(backendRootPath, ...relativePath.split('/'));
    if (!fs.existsSync(fullPath)) {
      throw new Error(`Backend resource listed in manifest is missing: ${relativePath}`);
    }
    const actualHash = sha256File(fullPath);
    if (actualHash !== expectedHash) {
      throw new Error(`Backend resource hash mismatch for ${relativePath}`);
    }
  }

  for (const relativePath of walkBackendFiles(backendRootPath)) {
    if (!manifestFiles.has(relativePath)) {
      throw new Error(`Backend resource file is not listed in integrity manifest: ${relativePath}`);
    }
  }
  return true;
}

module.exports = {
  aclGrantsStandardUserWrite,
  assertProcessElevated,
  appendBackendStartupLog,
  backendConfigPath,
  backendLogPath,
  backendManifestPath,
  backendRoot,
  closeBackendLogStream,
  createBackendLogStream,
  isProcessElevated,
  isPathUnderTrustedRoot,
  isPathWritableByStandardUsers,
  isWindowsStartupTaskEnabled,
  preflightPythonRuntime,
  resolvePackagedPythonCommand,
  resolvePythonCommand,
  runPythonProbe,
  setWindowsStartupTask,
  validatePythonProvenance,
  verifyBackendResourceIntegrity,
  WINDOWS_STARTUP_TASK_NAME
};

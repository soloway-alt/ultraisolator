#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const asar = require('@electron/asar');
const runtime = require('../backend-runtime');

const uiRoot = path.resolve(__dirname, '..');
const packageConfig = require('../package.json');

function findPackagedBackendRoot() {
  const outputDir = path.join(uiRoot, packageConfig.build.directories.output || 'dist-packaged');
  const candidates = [
    path.join(outputDir, 'win-unpacked', 'resources', 'backend'),
    path.join(outputDir, 'win-ia32-unpacked', 'resources', 'backend'),
    path.join(outputDir, 'win-arm64-unpacked', 'resources', 'backend')
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error(`No packaged resources/backend directory found under ${outputDir}. Run npm --prefix ui run pack or build first.`);
}

function findPackagedManifestPath(backendRoot) {
  const resourcesRoot = path.dirname(backendRoot);
  const appAsar = path.join(resourcesRoot, 'app.asar');
  if (fs.existsSync(appAsar)) {
    const bytes = asar.extractFile(appAsar, 'backend-manifest.json');
    return {
      manifestPath: path.join(appAsar, 'backend-manifest.json'),
      manifest: JSON.parse(Buffer.from(bytes).toString('utf8'))
    };
  }

  const unpackedManifest = path.join(resourcesRoot, 'app', 'backend-manifest.json');
  if (fs.existsSync(unpackedManifest)) {
    return {
      manifestPath: unpackedManifest,
      manifest: JSON.parse(fs.readFileSync(unpackedManifest, 'utf8'))
    };
  }

  throw new Error(`No packaged backend-manifest.json found in app.asar or resources/app under ${resourcesRoot}.`);
}

function assertManifestCoversBuildConfig() {
  const files = packageConfig.build.files || [];
  if (!files.includes('backend-manifest.json')) {
    throw new Error('backend-manifest.json must be included in the trusted app bundle files.');
  }
  const scripts = packageConfig.scripts || {};
  if (!scripts['build:backend-manifest'] || !scripts['build:python-runtime'] || !scripts['verify:packaged-runtime']) {
    throw new Error('package scripts must build the backend manifest and Python runtime before verification.');
  }
  const buildScript = scripts.build || '';
  if (!buildScript.includes('build:backend-manifest') || !buildScript.includes('build:python-runtime')) {
    throw new Error('production build must generate the backend manifest and Python runtime before packaging.');
  }
  const extraResources = packageConfig.build.extraResources || [];
  const bundledPython = extraResources.some((resource) => (
    resource && resource.from === '.runtime/python' && resource.to === 'python'
  ));
  if (!bundledPython) {
    throw new Error('production build must copy .runtime/python to resources/python.');
  }
}

function assertPackagedPythonPolicy(resourcesRoot, options = {}) {
  const command = 'C:\\Users\\attacker\\python.exe';
  let rejectedArbitraryPython = false;
  try {
    runtime.resolvePackagedPythonCommand({
      env: { EII_PYTHON: command },
      app: { isPackaged: true },
      trustedRoots: ['C:\\Program Files\\Esports Isolator PRO\\python'],
      isPathWritableByStandardUsers: () => false
    });
  } catch (error) {
    if (String(error.message).toLowerCase().includes('trusted')) {
      rejectedArbitraryPython = true;
    } else {
      throw error;
    }
  }
  if (!rejectedArbitraryPython) {
    throw new Error('production packaged runtime accepted arbitrary EII_PYTHON.');
  }

  const bundledPythonPath = path.join(resourcesRoot, 'python', 'python.exe');
  return runtime.resolvePackagedPythonCommand({
    env: {},
    app: { isPackaged: true },
    bundledPythonPath,
    trustedRoots: [path.dirname(bundledPythonPath)],
    // Callers verifying an artifact extracted into a temp directory must
    // bypass the ACL probe (temp is user-writable by design).
    isPathWritableByStandardUsers: options.isPathWritableByStandardUsers || runtime.isPathWritableByStandardUsers
  });
}

function runPackagedPython(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    windowsHide: true,
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  if (result.error || result.status !== 0) {
    const detail = result.error ? result.error.message : (result.stderr || result.stdout).trim();
    throw new Error(`Packaged Python probe failed: ${detail}`);
  }
  return result.stdout.trim();
}

function assertPackagedPythonWorks(command, resourcesRoot, backendRoot) {
  const versionText = runPackagedPython(command, ['--version'], backendRoot);
  const version = versionText.match(/Python\s+(\d+)\.(\d+)/);
  if (!version || Number(version[1]) !== 3 || Number(version[2]) < 12) {
    throw new Error(`Packaged Python 3.12 or newer is required; found ${versionText || 'unknown'}.`);
  }

  const dependencyText = runPackagedPython(command, ['-I', '-c', [
    'import json, psutil, sys',
    'print(json.dumps({"prefix": sys.prefix, "psutil": psutil.__version__}))'
  ].join('; ')], backendRoot);
  const dependency = JSON.parse(dependencyText);
  const expectedPrefix = path.resolve(resourcesRoot, 'python').toLowerCase();
  if (path.resolve(dependency.prefix).toLowerCase() !== expectedPrefix) {
    throw new Error(`Packaged Python resolved outside resources/python: ${dependency.prefix}`);
  }

  runPackagedPython(command, ['-c', 'import isolator, server; print("backend-import-ok")'], backendRoot);
}

function verifyPackagedRuntime(backendRoot, options = {}) {
  const resourcesRoot = path.dirname(backendRoot);
  const packagedPython = assertPackagedPythonPolicy(resourcesRoot, options);
  assertPackagedPythonWorks(packagedPython, resourcesRoot, backendRoot);
  const packagedManifest = findPackagedManifestPath(backendRoot);
  runtime.verifyBackendResourceIntegrity({
    backendRoot,
    manifestPath: packagedManifest.manifestPath,
    manifest: packagedManifest.manifest
  });
}

function main() {
  assertManifestCoversBuildConfig();
  const backendRoot = process.argv[2] ? path.resolve(process.argv[2]) : findPackagedBackendRoot();
  verifyPackagedRuntime(backendRoot);
  console.log(`packaged runtime verified: ${backendRoot}`);
}

// Importing this module (verify-installed-artifacts.js does) must not run
// the CLI verification as a side effect; that made every consumer require a
// packaged build on disk.
if (require.main === module) {
  main();
}

module.exports = { verifyPackagedRuntime };

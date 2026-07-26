#!/usr/bin/env node

const { spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const packageConfig = require('../package.json');
const { verifyPackagedRuntime } = require('./verify-packaged-runtime');

const uiRoot = path.resolve(__dirname, '..');
const outputDir = path.join(uiRoot, packageConfig.build.directories.output || 'dist-packaged');
const releaseDevSkipFlag = 'EII_RELEASE_DEV_SKIP_INSTALLED_ARTIFACT_VERIFY';
const checksumManifestName = 'SHA256SUMS.txt';

function expectedArtifactNames(version = packageConfig.version) {
  return [
    `Esports Isolator PRO Setup ${version}.exe`
  ];
}

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function assertNonEmptyFile(filePath, category) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${category} is missing.`);
  }
  const stat = fs.statSync(filePath);
  if (!stat.isFile() || stat.size <= 0) {
    throw new Error(`${category} is empty or not a file.`);
  }
}

function readChecksumManifest(manifestPath) {
  assertNonEmptyFile(manifestPath, checksumManifestName);
  return fs.readFileSync(manifestPath, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0);
}

function verifyReleaseArtifacts(options = {}) {
  const distDir = path.resolve(options.distDir || outputDir);
  const version = options.version || packageConfig.version;
  const expectedArtifacts = options.expectedArtifacts || expectedArtifactNames(version);
  const allowedRootFiles = new Set([...expectedArtifacts, checksumManifestName]);

  if (!fs.existsSync(distDir)) {
    throw new Error(`Release output directory is missing: ${distDir}`);
  }

  for (const artifact of expectedArtifacts) {
    assertNonEmptyFile(path.join(distDir, artifact), `${artifact} release artifact`);
  }

  const rootFiles = fs.readdirSync(distDir, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name);
  const unexpected = rootFiles.filter((name) => !allowedRootFiles.has(name));
  if (unexpected.length > 0) {
    throw new Error(`Unexpected root release artifact(s): ${unexpected.join(', ')}`);
  }

  const lines = readChecksumManifest(path.join(distDir, checksumManifestName));
  if (lines.length !== expectedArtifacts.length) {
    throw new Error(`${checksumManifestName} must contain exactly ${expectedArtifacts.length} artifact line(s).`);
  }

  const checksums = new Map();
  for (const line of lines) {
    const match = line.match(/^([a-f0-9]{64}) {2}(.+)$/);
    if (!match) {
      throw new Error(`${checksumManifestName} contains an invalid checksum line.`);
    }
    checksums.set(match[2], match[1]);
  }

  for (const artifact of expectedArtifacts) {
    const expectedHash = checksums.get(artifact);
    if (!expectedHash) {
      throw new Error(`${checksumManifestName} is missing ${artifact}.`);
    }
    const actualHash = sha256File(path.join(distDir, artifact));
    if (actualHash !== expectedHash) {
      throw new Error(`${checksumManifestName} hash mismatch for ${artifact}.`);
    }
  }

  const extraChecksums = [...checksums.keys()].filter((name) => !allowedRootFiles.has(name));
  if (extraChecksums.length > 0) {
    throw new Error(`${checksumManifestName} lists unexpected artifact(s): ${extraChecksums.join(', ')}`);
  }
}

function commandWorks(command) {
  const result = spawnSync(command, ['--help'], {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
  return !result.error && result.status === 0;
}

function resolveSevenZipCommand() {
  if (process.env.EII_SEVEN_ZIP) {
    const configured = path.resolve(process.env.EII_SEVEN_ZIP);
    if (!fs.existsSync(configured)) {
      throw new Error(`EII_SEVEN_ZIP points to a missing extractor: ${configured}`);
    }
    return configured;
  }

  const candidates = process.platform === 'win32'
    ? [
        '7z',
        '7za',
        path.join(process.env.ProgramFiles || 'C:\\Program Files', '7-Zip', '7z.exe'),
        path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', '7-Zip', '7z.exe')
      ]
    : ['7z', '7za'];

  for (const candidate of candidates) {
    if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
      continue;
    }
    if (commandWorks(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    'Installed artifact verification requires 7-Zip to inspect the NSIS payload. ' +
    'Install 7-Zip or set EII_SEVEN_ZIP to a trusted 7z.exe path. ' +
    `For local development only, set ${releaseDevSkipFlag}=1 to skip this fail-closed release check.`
  );
}

function runSevenZip(command, args, category) {
  const result = spawnSync(command, args, {
    windowsHide: true,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
  if (result.error || result.status !== 0) {
    const detail = result.error ? result.error.message : `exit code ${result.status}`;
    throw new Error(`${category} extraction failed (${detail}).`);
  }
}

function extractArchive(archivePath, destination, category, sevenZipCommand) {
  fs.mkdirSync(destination, { recursive: true });
  runSevenZip(sevenZipCommand, ['x', '-y', '-bd', `-o${destination}`, archivePath], category);
}

function walk(root, predicate, output = []) {
  if (!fs.existsSync(root)) {
    return output;
  }
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      walk(fullPath, predicate, output);
    }
    if (predicate(fullPath, entry)) {
      output.push(fullPath);
    }
  }
  return output;
}

function extractNestedArchives(root, category, sevenZipCommand) {
  const extracted = new Set();
  for (let pass = 0; pass < 4; pass += 1) {
    const archives = walk(root, (filePath, entry) =>
      entry.isFile() && path.extname(filePath).toLowerCase() === '.7z'
    ).filter((archivePath) => !extracted.has(archivePath));
    if (archives.length === 0) {
      return;
    }
    for (const archivePath of archives) {
      extracted.add(archivePath);
      extractArchive(archivePath, `${archivePath}.extracted`, category, sevenZipCommand);
    }
  }
}

function findBackendRoots(root) {
  return walk(root, (directory, entry) =>
    entry.isDirectory() &&
    path.basename(directory).toLowerCase() === 'backend' &&
    path.basename(path.dirname(directory)).toLowerCase() === 'resources'
  );
}

function sanitizeDiagnostic(message, contexts = []) {
  let sanitized = String(message || '');
  const ordered = contexts
    .filter((context) => context && context.root)
    .sort((left, right) => String(right.root).length - String(left.root).length);
  for (const context of ordered) {
    const escapedRoot = path.resolve(context.root).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    sanitized = sanitized.replace(new RegExp(escapedRoot, 'gi'), `[${context.category}]`);
  }
  return sanitized;
}

function verifyBackendRoots(category, backendRoots, contexts, options = {}) {
  if (backendRoots.length === 0) {
    throw new Error(`${category} artifact does not contain resources/backend.`);
  }
  for (const backendRoot of backendRoots) {
    try {
      verifyPackagedRuntime(backendRoot, options);
    } catch (error) {
      throw new Error(`${category} artifact runtime verification failed: ${sanitizeDiagnostic(error.message, contexts)}`);
    }
  }
}

function verifyExtractedArtifact(distDir, artifactName, category, tempRoot, sevenZipCommand) {
  const artifactPath = path.join(distDir, artifactName);
  assertNonEmptyFile(artifactPath, `${category} artifact`);
  const extractRoot = path.join(tempRoot, category);
  extractArchive(artifactPath, extractRoot, category, sevenZipCommand);
  extractNestedArchives(extractRoot, category, sevenZipCommand);
  verifyBackendRoots(
    category,
    findBackendRoots(extractRoot),
    [{ category, root: extractRoot }],
    { isPathWritableByStandardUsers: () => false }
  );
}

function verifyWinUnpackedIfPresent(distDir) {
  const appRoot = path.join(distDir, 'win-unpacked');
  const backendRoot = path.join(appRoot, 'resources', 'backend');
  if (!fs.existsSync(appRoot)) {
    return;
  }
  verifyBackendRoots('win-unpacked', [backendRoot], [{ category: 'win-unpacked', root: appRoot }]);
}

function verifyInstalledArtifacts(options = {}) {
  const distDir = path.resolve(options.distDir || outputDir);
  const version = options.version || packageConfig.version;
  const artifacts = expectedArtifactNames(version);
  verifyReleaseArtifacts({ distDir, version, expectedArtifacts: artifacts });

  const sevenZipCommand = options.sevenZipCommand || resolveSevenZipCommand();
  verifyWinUnpackedIfPresent(distDir);

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'eii-installed-artifacts-'));
  try {
    verifyExtractedArtifact(distDir, artifacts[0], 'installer', tempRoot, sevenZipCommand);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

function main() {
  if (process.env[releaseDevSkipFlag] === '1') {
    console.warn(`${releaseDevSkipFlag}=1: skipping installed and portable artifact verification.`);
    return;
  }
  verifyInstalledArtifacts({ distDir: process.argv[2] || outputDir });
  console.log('installed artifact verification passed');
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.message || error);
    process.exit(1);
  }
}

module.exports = {
  checksumManifestName,
  expectedArtifactNames,
  extractNestedArchives,
  findBackendRoots,
  main,
  releaseDevSkipFlag,
  resolveSevenZipCommand,
  sanitizeDiagnostic,
  verifyInstalledArtifacts,
  verifyReleaseArtifacts
};

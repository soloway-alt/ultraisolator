#!/usr/bin/env node

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const uiRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(uiRoot, '..');
const outputPath = path.join(uiRoot, 'backend-manifest.json');

const resourceInputs = [
  { from: path.join(repoRoot, 'server'), to: 'server' },
  { from: path.join(repoRoot, 'isolator'), to: 'isolator' },
  { from: path.join(repoRoot, 'best_isolator.py'), to: 'best_isolator.py' },
  { from: path.join(repoRoot, 'config.json.example'), to: 'config.json.example' },
  { from: path.join(repoRoot, 'requirements.txt'), to: 'requirements.txt' }
];

const ignoredDirectories = new Set(['__pycache__', '.pytest_cache']);
const ignoredExtensions = new Set(['.pyc', '.pyo', '.tmp', '.log']);

function toManifestPath(value) {
  return value.split(path.sep).join('/');
}

function hashFile(filePath) {
  // Normalize CRLF to LF before hashing so the digest does not depend on how
  // git materialized line endings on the machine that generated the manifest
  // versus the machine (or CI runner) verifying it. Must stay byte-for-byte
  // identical to sha256File in ui/backend-runtime.js.
  const raw = fs.readFileSync(filePath);
  const normalized = raw.includes(0x0d)
    ? Buffer.from(raw.toString('latin1').replace(/\r\n/g, '\n'), 'latin1')
    : raw;
  return crypto.createHash('sha256').update(normalized).digest('hex');
}

function shouldIgnore(filePath) {
  const parts = filePath.split(path.sep);
  return parts.some((part) => ignoredDirectories.has(part)) ||
    ignoredExtensions.has(path.extname(filePath).toLowerCase());
}

function addFile(files, sourcePath, manifestPath) {
  if (shouldIgnore(sourcePath)) {
    return;
  }
  files[toManifestPath(manifestPath)] = `sha256-${hashFile(sourcePath)}`;
}

function addDirectory(files, sourceRoot, manifestRoot) {
  for (const entry of fs.readdirSync(sourceRoot, { withFileTypes: true })) {
    const sourcePath = path.join(sourceRoot, entry.name);
    const manifestPath = path.posix.join(manifestRoot, entry.name);
    if (entry.isDirectory()) {
      if (!ignoredDirectories.has(entry.name)) {
        addDirectory(files, sourcePath, manifestPath);
      }
    } else if (entry.isFile()) {
      addFile(files, sourcePath, manifestPath);
    }
  }
}

function main() {
  const files = {};
  for (const input of resourceInputs) {
    if (!fs.existsSync(input.from)) {
      throw new Error(`Backend resource input is missing: ${input.from}`);
    }
    const stat = fs.statSync(input.from);
    if (stat.isDirectory()) {
      addDirectory(files, input.from, input.to);
    } else if (stat.isFile()) {
      addFile(files, input.from, input.to);
    }
  }

  const sortedFiles = {};
  for (const key of Object.keys(files).sort()) {
    sortedFiles[key] = files[key];
  }
  const manifest = {
    version: 1,
    algorithm: 'sha256',
    generatedAt: new Date(0).toISOString(),
    files: sortedFiles
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  console.log(`wrote ${outputPath} (${Object.keys(sortedFiles).length} files)`);
}

main();

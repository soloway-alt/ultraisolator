// Node-only locale tooling: scans ui/src for referenced catalog keys so the
// unit suite can fail on orphans. Kept out of validate.mjs because that
// module ships in the renderer bundle and this one needs fs.
import fs from 'node:fs';
import path from 'node:path';

// Static references: t('key'), notice objects ({ key: 'x.y' }), and
// data-driven catalog keys declared in constants (labelKey: 'nav.x').
const STATIC_PATTERNS = [
  /\bt\(\s*'([^']+)'/g,
  /\bkey:\s*'([^']+)'/g,
  /\blabelKey:\s*'([^']+)'/g
];
// validationError('x', …) produces the catalog key `validation.x`.
const VALIDATION_ERROR_PATTERN = /\bvalidationError\(\s*'([^']+)'/g;
// Dynamic references: t(`prefix.${…}`) marks every key under the prefix used.
const DYNAMIC_PATTERN = /\bt\(\s*`([^`$]*)\$\{/g;

export function collectUsedKeys(sourceDir) {
  const used = new Set();
  const dynamicPrefixes = new Set();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (/\.(jsx|js|mjs)$/.test(entry.name)) {
        const source = fs.readFileSync(full, 'utf8');
        for (const pattern of STATIC_PATTERNS) {
          for (const match of source.matchAll(pattern)) {
            used.add(match[1]);
          }
        }
        for (const match of source.matchAll(VALIDATION_ERROR_PATTERN)) {
          used.add(`validation.${match[1]}`);
        }
        for (const match of source.matchAll(DYNAMIC_PATTERN)) {
          if (match[1]) {
            dynamicPrefixes.add(match[1]);
          }
        }
      }
    }
  };
  walk(sourceDir);
  return { used, dynamicPrefixes };
}

// `allowPrefixes` covers keys referenced only through runtime data the
// scanner cannot see (e.g. notification title_key/message_key frames sent by
// the backend).
export function assertNoOrphanKeys(catalog, sourceDir, allowPrefixes = []) {
  const { used, dynamicPrefixes } = collectUsedKeys(sourceDir);
  const prefixes = [...dynamicPrefixes, ...allowPrefixes];
  const orphans = Object.keys(catalog).filter((key) => (
    !used.has(key) && !prefixes.some((prefix) => key.startsWith(prefix))
  ));
  if (orphans.length) {
    throw new Error(
      `Orphan locale keys (in the catalog, never referenced from ${sourceDir}):\n${orphans.join('\n')}`
    );
  }
}

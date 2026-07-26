import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const metricCard = readFileSync(`${SRC}components/cards/MetricCard.jsx`, 'utf8');
const styles = readFileSync(`${SRC}styles.css`, 'utf8');

// Collect the STATIC class tokens MetricCard emits: the literals in every
// className="..." attribute plus the quoted strings in the `classes` array.
// Dynamic values (the tone/className identifiers) are not literals, so they
// are excluded — a tone with no rule is a harmless extra class.
function staticClassTokens(source) {
  const tokens = new Set();
  for (const match of source.matchAll(/className="([^"]+)"/g)) {
    for (const token of match[1].split(/\s+/)) {
      if (token) tokens.add(token);
    }
  }
  const arrayLiteral = source.match(/const classes = \[([^\]]*)\]/);
  if (arrayLiteral) {
    for (const match of arrayLiteral[1].matchAll(/'([a-z][a-z-]*)'/g)) {
      tokens.add(match[1]);
    }
  }
  return [...tokens];
}

test('every static class MetricCard emits is defined in styles.css', () => {
  const tokens = staticClassTokens(metricCard);
  // Sanity: the extractor found the label/value/detail child classes.
  assert.ok(tokens.length >= 3, `expected several class tokens, got ${tokens.join(', ')}`);
  const missing = tokens.filter((token) => !styles.includes(`.${token}`));
  assert.deepEqual(
    missing,
    [],
    `MetricCard emits class tokens with no selector in styles.css: ${missing.join(', ')}`
  );
});

import test from 'node:test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { en } from '../src/locales/en.mjs';
import { ru } from '../src/locales/ru.mjs';
import { assertNoOrphanKeys } from '../src/locales/check.mjs';
import { assertLocaleParity } from '../src/locales/validate.mjs';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');

test('English and Russian locales have matching keys and placeholders', () => {
  assertLocaleParity({ en, ru });
});

test('every catalog key is referenced from ui/src', () => {
  // notification.* keys arrive as title_key/message_key in backend frames,
  // invisible to the static scanner.
  assertNoOrphanKeys(en, SRC, ['notification.']);
});

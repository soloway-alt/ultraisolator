import assert from 'node:assert/strict';
import test from 'node:test';
import { processMatchesFilter, processMatchesQuery } from '../src/utils/processFilters.mjs';

test('the all filter matches every row', () => {
  assert.equal(processMatchesFilter({}, 'all'), true);
  assert.equal(processMatchesFilter({ status: 'jailed' }, 'all'), true);
});

test('the game filter matches any of the four game signals', () => {
  assert.equal(processMatchesFilter({ game: true }, 'game'), true);
  assert.equal(processMatchesFilter({ status: 'game' }, 'game'), true);
  assert.equal(processMatchesFilter({ source: 'observed_game' }, 'game'), true);
  assert.equal(processMatchesFilter({ tuning_state: 'applied' }, 'game'), true);
  assert.equal(processMatchesFilter({ status: 'tracked' }, 'game'), false);
});

test('the protected filter matches the flag or the status', () => {
  assert.equal(processMatchesFilter({ protected: true }, 'protected'), true);
  assert.equal(processMatchesFilter({ status: 'protected' }, 'protected'), true);
  assert.equal(processMatchesFilter({ status: 'jailed' }, 'protected'), false);
});

test('other filters require an exact status match', () => {
  assert.equal(processMatchesFilter({ status: 'jailed' }, 'jailed'), true);
  assert.equal(processMatchesFilter({ status: 'tracked' }, 'jailed'), false);
});

test('an empty query matches every row', () => {
  assert.equal(processMatchesQuery({ name: 'cs2.exe' }, ''), true);
});

test('the query searches pid, name, source, and status case-insensitively', () => {
  const row = { pid: 4242, name: 'CS2.exe', source: 'observed_game', status: 'game' };
  assert.equal(processMatchesQuery(row, '4242'), true);
  assert.equal(processMatchesQuery(row, 'cs2'), true);
  assert.equal(processMatchesQuery(row, 'observed'), true);
  assert.equal(processMatchesQuery(row, 'game'), true);
  assert.equal(processMatchesQuery(row, 'valorant'), false);
});

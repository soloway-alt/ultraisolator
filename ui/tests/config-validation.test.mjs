import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseListValue,
  validateAppProfilesDraft,
  validateConfigDraft
} from '../src/utils/config.mjs';

// Minimal schema mirroring the /api/config/defaults shapes the renderer sees.
const SCHEMA = {
  housekeeping_cores: { type: 'int', min: 1, max: 16 },
  game_exit_restore_delay_s: { type: 'float', min: 0, max: 300 },
  anti_cheat_mode: { type: 'choice', choices: ['aggressive', 'conservative'] },
  enable_background_jailing: { type: 'bool' },
  games: { type: 'string_list' },
  log_file: { type: 'string' }
};

const PROFILE_SPEC = {
  type: 'app_profiles',
  priority_choices: ['idle', 'below_normal', 'normal', 'above_normal', 'high']
};

const VALID_DRAFT = {
  housekeeping_cores: '2',
  game_exit_restore_delay_s: '10',
  anti_cheat_mode: 'conservative',
  enable_background_jailing: true,
  games: 'cs2.exe\nvalorant.exe',
  log_file: ''
};

test('a valid draft converts every field to its backend type', () => {
  const { config, errors } = validateConfigDraft(VALID_DRAFT, SCHEMA);
  assert.deepEqual(errors, {});
  assert.deepEqual(config, {
    housekeeping_cores: 2,
    game_exit_restore_delay_s: 10,
    anti_cheat_mode: 'conservative',
    enable_background_jailing: true,
    games: ['cs2.exe', 'valorant.exe'],
    log_file: ''
  });
});

test('int fields reject float strings', () => {
  const { config, errors } = validateConfigDraft({ ...VALID_DRAFT, housekeeping_cores: '2.5' }, SCHEMA);
  assert.equal(errors.housekeeping_cores.key, 'validation.integer');
  assert.equal('housekeeping_cores' in config, false);
});

test('numeric fields reject blank and non-numeric text', () => {
  const blank = validateConfigDraft({ ...VALID_DRAFT, housekeeping_cores: '   ' }, SCHEMA);
  assert.equal(blank.errors.housekeeping_cores.key, 'validation.required');
  const text = validateConfigDraft({ ...VALID_DRAFT, housekeeping_cores: 'four' }, SCHEMA);
  assert.equal(text.errors.housekeeping_cores.key, 'validation.number');
});

test('numeric fields reject out-of-bounds values', () => {
  const low = validateConfigDraft({ ...VALID_DRAFT, housekeeping_cores: '0' }, SCHEMA);
  assert.equal(low.errors.housekeeping_cores.key, 'validation.minimum');
  const high = validateConfigDraft({ ...VALID_DRAFT, housekeeping_cores: '17' }, SCHEMA);
  assert.equal(high.errors.housekeeping_cores.key, 'validation.maximum');
  const float = validateConfigDraft({ ...VALID_DRAFT, game_exit_restore_delay_s: '300.5' }, SCHEMA);
  assert.equal(float.errors.game_exit_restore_delay_s.key, 'validation.maximum');
});

test('float fields accept fractional values', () => {
  const { config, errors } = validateConfigDraft({ ...VALID_DRAFT, game_exit_restore_delay_s: '2.5' }, SCHEMA);
  assert.deepEqual(errors, {});
  assert.equal(config.game_exit_restore_delay_s, 2.5);
});

test('choice fields enforce membership and normalize case', () => {
  const invalid = validateConfigDraft({ ...VALID_DRAFT, anti_cheat_mode: 'balanced' }, SCHEMA);
  assert.equal(invalid.errors.anti_cheat_mode.key, 'validation.choice');
  assert.equal('anti_cheat_mode' in invalid.config, false);
  const upper = validateConfigDraft({ ...VALID_DRAFT, anti_cheat_mode: '  AGGRESSIVE ' }, SCHEMA);
  assert.deepEqual(upper.errors, {});
  assert.equal(upper.config.anti_cheat_mode, 'aggressive');
});

test('bool fields coerce truthy and falsy drafts', () => {
  assert.equal(validateConfigDraft({ ...VALID_DRAFT, enable_background_jailing: 1 }, SCHEMA).config.enable_background_jailing, true);
  assert.equal(validateConfigDraft({ ...VALID_DRAFT, enable_background_jailing: '' }, SCHEMA).config.enable_background_jailing, false);
});

test('string_list fields split on newlines and commas via parseListValue', () => {
  const { config } = validateConfigDraft({ ...VALID_DRAFT, games: ' cs2.exe ,\n\nvalorant.exe\r\ndota2.exe ' }, SCHEMA);
  assert.deepEqual(config.games, ['cs2.exe', 'valorant.exe', 'dota2.exe']);
  assert.deepEqual(parseListValue(['  a.exe ', '', 'b.exe']), ['a.exe', 'b.exe']);
  assert.deepEqual(parseListValue(null), []);
});

test('app_profiles reject duplicate executables case-insensitively', () => {
  const { errors } = validateAppProfilesDraft([
    { exe: 'OBS64.exe', enabled: true },
    { exe: 'obs64.exe', enabled: true }
  ], PROFILE_SPEC);
  assert.equal(errors['app_profiles[1].exe'].key, 'validation.duplicateExecutable');
  assert.deepEqual(errors['app_profiles[1].exe'].params, { exe: 'obs64.exe' });
});

test('app_profiles reject never_jail combined with always_jail', () => {
  const { errors } = validateAppProfilesDraft([
    { exe: 'obs64.exe', never_jail: true, always_jail: true }
  ], PROFILE_SPEC);
  assert.equal(errors['app_profiles[0]'].key, 'validation.profileRuleConflict');
});

test('app_profiles require an executable and validate priority membership', () => {
  const { profiles, errors } = validateAppProfilesDraft([
    { exe: '', priority_class: 'realtime' }
  ], PROFILE_SPEC);
  assert.equal(errors['app_profiles[0].exe'].key, 'validation.executableRequired');
  assert.equal(errors['app_profiles[0].priority_class'].key, 'validation.priorityChoice');
  assert.equal(profiles.length, 1);
});

test('app_profiles normalize entries and flow through validateConfigDraft', () => {
  const schema = { app_profiles: PROFILE_SPEC };
  const { config, errors } = validateConfigDraft({
    app_profiles: [{ exe: ' OBS64.EXE ', enabled: 1, treat_as_game: 0, priority_class: ' HIGH ' }]
  }, schema);
  assert.deepEqual(errors, {});
  assert.deepEqual(config.app_profiles, [{
    exe: 'obs64.exe',
    enabled: true,
    treat_as_game: false,
    never_jail: false,
    always_jail: false,
    priority_class: 'high'
  }]);
});

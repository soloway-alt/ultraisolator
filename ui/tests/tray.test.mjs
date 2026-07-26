import assert from 'node:assert/strict';
import test from 'node:test';
import tray from '../main/tray.js';

const {
  TRAY_STATE_COLORS,
  normalizeTrayStatus,
  trayErrorMenuTemplate,
  trayIconSvg,
  trayMenuTemplate,
  trayStateForStatus,
  trayTooltip
} = tray;

test('trayIconSvg paints the state color and falls back to idle', () => {
  for (const state of ['idle', 'game', 'error']) {
    assert.ok(trayIconSvg(state).includes(TRAY_STATE_COLORS[state]), `${state} icon must use its color`);
  }
  assert.ok(trayIconSvg('unknown').includes(TRAY_STATE_COLORS.idle));
});

test('trayTooltip names the state', () => {
  assert.equal(trayTooltip('game'), 'UltraIsolator - game');
});

test('normalizeTrayStatus coerces missing and truthy fields to booleans', () => {
  assert.deepEqual(normalizeTrayStatus(null), { running: false, game_mode: false });
  assert.deepEqual(normalizeTrayStatus({ running: 1, game_mode: 'yes' }), { running: true, game_mode: true });
  assert.deepEqual(normalizeTrayStatus({ running: true }), { running: true, game_mode: false });
});

test('trayStateForStatus maps game mode to the game icon', () => {
  assert.equal(trayStateForStatus({ running: true, game_mode: true }), 'game');
  assert.equal(trayStateForStatus({ running: true, game_mode: false }), 'idle');
  assert.equal(trayStateForStatus({ running: false, game_mode: false }), 'idle');
});

test('the tray menu offers Stop while running and Start otherwise', () => {
  const onStart = () => {};
  const onStop = () => {};
  const handlers = { onShow: () => {}, onStart, onStop, onQuit: () => {} };

  const runningMenu = trayMenuTemplate({ running: true, ...handlers });
  assert.deepEqual(runningMenu.map((item) => item.label ?? item.type), [
    'Open Dashboard', 'separator', 'Stop Isolator', 'separator', 'Exit'
  ]);
  assert.equal(runningMenu[2].click, onStop);

  const stoppedMenu = trayMenuTemplate({ running: false, ...handlers });
  assert.equal(stoppedMenu[2].label, 'Start Isolator');
  assert.equal(stoppedMenu[2].click, onStart);
});

test('the error menu explains the failure and offers Retry and Exit', () => {
  const onRetry = () => {};
  const onQuit = () => {};
  const menu = trayErrorMenuTemplate({ onRetry, onQuit });
  assert.equal(menu[0].label, 'Backend failed to start');
  assert.equal(menu[0].enabled, false);
  assert.equal(menu.find((item) => item.label === 'Retry').click, onRetry);
  assert.equal(menu.find((item) => item.label === 'Exit').click, onQuit);
});

// Tray decision logic: icon artwork, tooltip text, status mapping, and menu
// templates. No Electron imports — electron-main.js owns the Tray/Menu/
// nativeImage glue and feeds click handlers in.

const TRAY_STATE_COLORS = Object.freeze({
  idle: '#6F7782',
  game: '#00D4AA',
  error: '#FF4757'
});

function trayIconSvg(state) {
  const color = TRAY_STATE_COLORS[state] || TRAY_STATE_COLORS.idle;
  return [
    '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">',
    '<rect width="32" height="32" rx="6" fill="#0A0A0A"/>',
    `<path d="M16 4 26 9v7c0 6.3-4 10.8-10 12-6-1.2-10-5.7-10-12V9l10-5Z" fill="${color}" opacity="0.95"/>`,
    '<path d="M16 8 22 11.1v4.7c0 3.7-2.2 6.4-6 7.4-3.8-1-6-3.7-6-7.4v-4.7L16 8Z" fill="#0A0A0A" opacity="0.88"/>',
    `<path d="M16 11.2 19.8 13.1v3.1c0 2.2-1.3 3.8-3.8 4.6-2.5-.8-3.8-2.4-3.8-4.6v-3.1l3.8-1.9Z" fill="${color}"/>`,
    '</svg>'
  ].join('');
}

function trayTooltip(state) {
  return `UltraIsolator - ${state}`;
}

function normalizeTrayStatus(status) {
  return {
    running: Boolean(status && status.running),
    game_mode: Boolean(status && status.game_mode)
  };
}

function trayStateForStatus(status) {
  return status.game_mode ? 'game' : 'idle';
}

function trayMenuTemplate({ running, onShow, onStart, onStop, onQuit }) {
  return [
    { label: 'Open Dashboard', click: onShow },
    { type: 'separator' },
    { label: running ? 'Stop Isolator' : 'Start Isolator', click: running ? onStop : onStart },
    { type: 'separator' },
    { label: 'Exit', click: onQuit }
  ];
}

function trayErrorMenuTemplate({ onRetry, onQuit }) {
  return [
    { label: 'Backend failed to start', enabled: false },
    { type: 'separator' },
    { label: 'Retry', click: onRetry },
    { label: 'Exit', click: onQuit }
  ];
}

module.exports = {
  TRAY_STATE_COLORS,
  normalizeTrayStatus,
  trayErrorMenuTemplate,
  trayIconSvg,
  trayMenuTemplate,
  trayStateForStatus,
  trayTooltip
};

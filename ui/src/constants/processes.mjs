export const PROCESS_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'game', label: 'Game' },
  { id: 'jailed', label: 'Background limited' },
  { id: 'foreground', label: 'Active app' },
  { id: 'protected', label: 'Protected' }
];

export const PROCESS_STATUS_LABELS = {
  game: 'Game',
  jailed: 'Background limited',
  foreground: 'Active app',
  protected: 'Left unchanged',
  tracked: 'Observed'
};

export const PRIORITY_CLASS_LABELS = {
  32: 'Normal',
  64: 'Idle',
  128: 'High',
  256: 'Realtime',
  16384: 'Below normal',
  32768: 'Above normal'
};

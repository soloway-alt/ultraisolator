import { createContext, useContext, useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { DEFAULT_APP_SETTINGS } from '../constants/settings.mjs';
import {
  loadAppSettings,
  normalizeAppSettings,
  normalizeAppSettingsPatch,
  saveAppSettings
} from '../utils/appSettings.mjs';
import { AppSettingsStore } from './AppSettingsStore.mjs';

const AppSettingsContext = createContext(null);

export function AppSettingsProvider({ children }) {
  const storeRef = useRef(null);
  if (!storeRef.current) {
    storeRef.current = new AppSettingsStore({
      initialSettings: DEFAULT_APP_SETTINGS,
      load: loadAppSettings,
      save: saveAppSettings,
      normalizeSettings: normalizeAppSettings,
      normalizePatch: normalizeAppSettingsPatch
    });
  }
  const store = storeRef.current;
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);

  useEffect(() => {
    store.initialize().catch(() => undefined);
  }, [store]);

  const value = useMemo(() => ({
    ...snapshot,
    updateSettings: (patch) => store.update(patch)
  }), [snapshot, store]);

  return <AppSettingsContext.Provider value={value}>{children}</AppSettingsContext.Provider>;
}

export function useAppSettings() {
  const value = useContext(AppSettingsContext);
  if (!value) {
    throw new Error('useAppSettings must be used inside AppSettingsProvider');
  }
  return value;
}

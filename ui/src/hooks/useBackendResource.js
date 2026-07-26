import { useCallback, useEffect, useRef, useState } from 'react';
import { requestJson } from '../utils/api.mjs';

// One load/refresh/error machine for the read-only backend resources
// (topology, logs, MSI, readiness, analysis) that previously each carried
// their own copy. `enabled: false` (game mode, hidden window) freezes the
// machine without issuing a request; changing `refreshKey` re-runs the load;
// `reload()` fetches `refreshPath` (falling back to `path`) for endpoints
// with an explicit ?refresh=1 variant.
//
// The error is a structured notice for translatedNotice(); requestJson only
// ever throws Error, so the fallback always carries the real message and the
// old `error instanceof Error ? ... : t(...)` dead branch is gone.
export function useBackendResource(path, { enabled = true, refreshKey = null, refreshPath = null } = {}) {
  const [data, setData] = useState(null);
  const [state, setState] = useState({ loading: true, refreshing: false, error: null });
  const dataRef = useRef(null);

  const load = useCallback(async (target) => {
    if (!enabled) {
      setState((current) => ({ ...current, loading: false, refreshing: false }));
      return;
    }
    setState({ loading: !dataRef.current, refreshing: Boolean(dataRef.current), error: null });
    try {
      const payload = await requestJson(target);
      dataRef.current = payload;
      setData(payload);
      setState({ loading: false, refreshing: false, error: null });
    } catch (error) {
      setState({
        loading: false,
        refreshing: false,
        error: { key: 'backend.requestFailed', fallback: error.message, params: {} }
      });
    }
  }, [enabled]);

  useEffect(() => {
    load(path);
    // refreshKey exists purely to re-run the load on coarse transitions.
  }, [load, path, refreshKey]);

  const reload = useCallback(() => load(refreshPath || path), [load, refreshPath, path]);

  return { data, loading: state.loading, refreshing: state.refreshing, error: state.error, reload };
}

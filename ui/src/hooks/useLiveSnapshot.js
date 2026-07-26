import { startTransition, useEffect, useMemo, useState } from 'react';

const MAX_NOTIFICATION_HISTORY = 80;

function isRendererVisible() {
  if (typeof document === 'undefined') {
    return true;
  }
  return document.visibilityState === 'visible';
}

function normalizeSnapshot(snapshot) {
  const processes = Array.isArray(snapshot?.processes) ? snapshot.processes : [];
  return {
    ...snapshot,
    processes
  };
}

function normalizeNotification(notification) {
  const fallbackId = `${notification?.type || 'event'}-${notification?.timestamp || Date.now()}`;
  const data = notification?.data && typeof notification.data === 'object' ? notification.data : {};
  return {
    id: notification?.id || fallbackId,
    type: notification?.type || 'event',
    key: notification?.key || notification?.code || notification?.type || 'event',
    title_key: notification?.title_key || data.title_key || null,
    message_key: notification?.message_key || data.message_key || null,
    data,
    severity: notification?.severity || 'info',
    title: notification?.title || 'Isolator event',
    message: notification?.message || '',
    timestamp: notification?.timestamp || Date.now() / 1000,
    suppress_in_game_mode: Boolean(notification?.suppress_in_game_mode)
  };
}

function appendNotification(current, notification) {
  const next = [normalizeNotification(notification), ...(current.notifications || [])];
  if (next.length > MAX_NOTIFICATION_HISTORY) {
    next.length = MAX_NOTIFICATION_HISTORY;
  }
  return {
    ...current,
    notifications: next
  };
}

function decodeLivePayload(data) {
  if (typeof data !== 'string') {
    return data;
  }
  return JSON.parse(data);
}

export function useLiveSnapshot() {
  const [visible, setVisible] = useState(() => isRendererVisible());
  const [state, setState] = useState({
    connectionState: isRendererVisible() ? 'idle' : 'paused',
    snapshot: null,
    notifications: [],
    lastUpdated: null,
    error: null
  });

  useEffect(() => {
    const updateVisibility = () => {
      setVisible(isRendererVisible());
    };
    const removeTrayListener = window.isolator?.onTrayShow?.(updateVisibility);

    document.addEventListener('visibilitychange', updateVisibility);
    window.addEventListener('focus', updateVisibility);
    window.addEventListener('blur', updateVisibility);
    updateVisibility();

    return () => {
      document.removeEventListener('visibilitychange', updateVisibility);
      window.removeEventListener('focus', updateVisibility);
      window.removeEventListener('blur', updateVisibility);
      if (typeof removeTrayListener === 'function') {
        removeTrayListener();
      }
    };
  }, []);

  useEffect(() => {
    if (!visible) {
      window.isolator?.stopLiveSnapshot?.();
      setState((current) => ({
        ...current,
        connectionState: 'paused',
        error: null
      }));
      return undefined;
    }

    if (!window.isolator?.startLiveSnapshot || !window.isolator?.onLiveSnapshot) {
      setState((current) => ({
        ...current,
        connectionState: 'error',
        error: 'live stream unavailable'
      }));
      return undefined;
    }

    let disposed = false;

    const handleSnapshot = (data) => {
      if (disposed) {
        return;
      }
      let snapshot;
      try {
        snapshot = normalizeSnapshot(decodeLivePayload(data));
      } catch (parseError) {
        console.error('[live] failed to parse snapshot frame', parseError);
        setState((current) => ({
          ...current,
          connectionState: 'error',
          error: 'malformed live frame'
        }));
        return;
      }
      startTransition(() => {
        setState((current) => ({
          connectionState: 'connected',
          snapshot,
          notifications: current.notifications,
          lastUpdated: new Date(),
          error: null
        }));
      });
    };

    const handleNotification = (data) => {
      if (disposed) {
        return;
      }
      let notification;
      try {
        notification = decodeLivePayload(data);
      } catch (parseError) {
        console.error('[live] failed to parse notification frame', parseError);
        setState((current) => ({
          ...current,
          connectionState: 'error',
          error: 'malformed notification frame'
        }));
        return;
      }
      startTransition(() => {
        setState((current) => appendNotification(current, notification));
      });
    };

    const handleLiveEvent = (event) => {
      if (disposed) {
        return;
      }
      const eventName = event?.eventName || 'message';
      if (eventName === 'state') {
        setState((current) => ({
          ...current,
          connectionState: event.data?.connectionState || current.connectionState,
          error: event.data?.error || null
        }));
      } else if (eventName === 'snapshot') {
        handleSnapshot(event.data);
      } else if (eventName === 'notification') {
        handleNotification(event.data);
      }
    };

    const removeLiveListener = window.isolator.onLiveSnapshot(handleLiveEvent);
    window.isolator.startLiveSnapshot().catch((error) => {
      if (!disposed) {
        setState((current) => ({
          ...current,
          connectionState: 'error',
          error: error instanceof Error ? error.message : 'live stream unavailable'
        }));
      }
    });

    return () => {
      disposed = true;
      if (typeof removeLiveListener === 'function') {
        removeLiveListener();
      }
      window.isolator?.stopLiveSnapshot?.();
    };
  }, [visible]);

  return useMemo(() => ({ ...state, visible }), [state, visible]);
}

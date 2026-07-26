import { startTransition, useEffect, useState } from 'react';

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
  const next = [normalizeNotification(notification), ...current];
  if (next.length > MAX_NOTIFICATION_HISTORY) {
    next.length = MAX_NOTIFICATION_HISTORY;
  }
  return next;
}

function decodeLivePayload(data) {
  if (typeof data !== 'string') {
    return data;
  }
  return JSON.parse(data);
}

// Live state is held in separate cells (connection, snapshot, notifications)
// so a snapshot tick does not invalidate notification consumers and a
// notification frame does not invalidate snapshot consumers.
export function useLiveSnapshot() {
  const [visible, setVisible] = useState(() => isRendererVisible());
  const [connection, setConnection] = useState({
    connectionState: isRendererVisible() ? 'idle' : 'paused',
    error: null
  });
  const [snapshot, setSnapshot] = useState(null);
  const [notifications, setNotifications] = useState([]);

  const setConnectionState = (connectionState, error = null) => {
    setConnection((current) => (
      current.connectionState === connectionState && current.error === error
        ? current
        : { connectionState, error }
    ));
  };

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
      setConnectionState('paused');
      return undefined;
    }

    if (!window.isolator?.startLiveSnapshot || !window.isolator?.onLiveSnapshot) {
      setConnectionState('error', 'live stream unavailable');
      return undefined;
    }

    let disposed = false;

    const handleSnapshot = (data) => {
      if (disposed) {
        return;
      }
      let nextSnapshot;
      try {
        nextSnapshot = normalizeSnapshot(decodeLivePayload(data));
      } catch (parseError) {
        console.error('[live] failed to parse snapshot frame', parseError);
        setConnectionState('error', 'malformed live frame');
        return;
      }
      startTransition(() => {
        setSnapshot(nextSnapshot);
        setConnectionState('connected');
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
        setConnectionState('error', 'malformed notification frame');
        return;
      }
      startTransition(() => {
        setNotifications((current) => appendNotification(current, notification));
      });
    };

    const handleLiveEvent = (event) => {
      if (disposed) {
        return;
      }
      const eventName = event?.eventName || 'message';
      if (eventName === 'state') {
        setConnection((current) => {
          const next = {
            connectionState: event.data?.connectionState || current.connectionState,
            error: event.data?.error || null
          };
          return next.connectionState === current.connectionState && next.error === current.error
            ? current
            : next;
        });
      } else if (eventName === 'snapshot') {
        handleSnapshot(event.data);
      } else if (eventName === 'notification') {
        handleNotification(event.data);
      }
    };

    const removeLiveListener = window.isolator.onLiveSnapshot(handleLiveEvent);
    window.isolator.startLiveSnapshot().catch((error) => {
      if (!disposed) {
        setConnectionState('error', error instanceof Error ? error.message : 'live stream unavailable');
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

  return {
    connectionState: connection.connectionState,
    error: connection.error,
    snapshot,
    notifications,
    visible
  };
}

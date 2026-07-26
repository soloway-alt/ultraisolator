// SSE relay between the backend /api/live endpoint and the renderer. No
// Electron imports: electron-main.js injects the HTTP client, backend
// location, auth token, and the renderer/tray sinks, so reconnect and
// frame-parsing behavior stays unit-testable.

function parseSseFrame(frame) {
  const lines = String(frame).split(/\r?\n/);
  const data = [];
  let eventName = 'message';
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).trimStart());
    }
  }
  return { eventName, data: data.join('\n') };
}

function createLiveStreamRelay({
  httpGet,
  getBackendUrl,
  getAuthToken,
  emit,
  onSnapshotStatus,
  reconnectDelayMs = 1500
}) {
  let request = null;
  let reconnectTimer = null;
  let stopped = true;
  let buffer = '';

  function scheduleReconnect(message) {
    if (stopped) {
      return;
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    emit({ eventName: 'state', data: { connectionState: 'error', error: message } });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, reconnectDelayMs);
    if (typeof reconnectTimer.unref === 'function') {
      reconnectTimer.unref();
    }
  }

  function handleFrame(frame) {
    const { eventName, data } = parseSseFrame(frame);
    if (eventName === 'snapshot') {
      try {
        const snapshot = JSON.parse(data);
        onSnapshotStatus(snapshot.status);
      } catch (_error) {
        emit({ eventName: 'state', data: { connectionState: 'error', error: 'malformed live frame' } });
        return;
      }
    }
    emit({ eventName, data });
  }

  function stop(options = {}) {
    stopped = true;
    buffer = '';
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (request) {
      const active = request;
      request = null;
      active.destroy();
    }
    if (options.notify !== false) {
      emit({ eventName: 'state', data: { connectionState: 'paused', error: null } });
    }
  }

  function open() {
    if (stopped) {
      return;
    }
    const backendUrl = getBackendUrl();
    if (!backendUrl) {
      scheduleReconnect('Backend is not ready.');
      return;
    }
    if (request) {
      return;
    }
    const url = new URL('/api/live', backendUrl);
    emit({ eventName: 'state', data: { connectionState: 'connecting', error: null } });
    const active = httpGet({
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      timeout: 0,
      headers: {
        Authorization: `Bearer ${getAuthToken()}`
      }
    }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        request = null;
        const message = `live stream failed with HTTP ${response.statusCode}`;
        // 401/403 mean the bearer token itself was rejected; retrying with
        // the same token cannot help, so report the error without scheduling
        // a reconnect.
        if (response.statusCode === 401 || response.statusCode === 403) {
          emit({ eventName: 'state', data: { connectionState: 'error', error: message } });
          return;
        }
        scheduleReconnect(message);
        return;
      }

      emit({ eventName: 'state', data: { connectionState: 'connected', error: null } });
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        buffer += chunk;
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        for (const frame of frames) {
          handleFrame(frame);
        }
      });
      response.on('end', () => {
        request = null;
        buffer = '';
        scheduleReconnect('live stream disconnected');
      });
    });
    request = active;
    active.on('error', (error) => {
      request = null;
      buffer = '';
      if (!stopped) {
        scheduleReconnect(error instanceof Error ? error.message : 'live stream unavailable');
      }
    });
  }

  function start() {
    if (request && !stopped) {
      return;
    }
    stopped = false;
    buffer = '';
    open();
  }

  return { start, stop };
}

module.exports = { createLiveStreamRelay, parseSseFrame };

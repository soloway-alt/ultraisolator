// Renderer URL resolution and sender trust checks for the dashboard window.
// No Electron imports: electron-main.js injects packaging state, the dist
// path, and the backend startup error, keeping this logic unit-testable.
const fs = require('fs');
const { pathToFileURL } = require('url');

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Single builder for every inline diagnostic/fallback page the main window
// can show; `message` must already be HTML-escaped by the caller.
function diagnosticPage({ accent, heading, message }) {
  const page = [
    '<!doctype html><html><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width,initial-scale=1">',
    '<title>UltraIsolator</title>',
    '<style>body{margin:0;background:#0A0A0A;color:#E8E8EC;font-family:Inter,Segoe UI,sans-serif}',
    `.shell{display:grid;place-items:center;min-height:100vh;padding:32px}.mark{color:${accent};font:700 20px Consolas,monospace;letter-spacing:.08em}`,
    '.sub{margin-top:10px;color:#AAAAAA;font-size:13px;max-width:720px;line-height:1.5}</style></head>',
    `<body><main class="shell"><div><div class="mark">${heading}</div>`,
    `<div class="sub">${message}</div></div></main></body></html>`
  ].join('');
  return `data:text/html;charset=utf-8,${encodeURIComponent(page)}`;
}

function rendererFailureUrl(detail) {
  return diagnosticPage({
    accent: '#FF4757',
    heading: 'RENDERER LOAD FAILED',
    message: escapeHtml(String(detail || 'Renderer failed to mount. Rebuild the dashboard and reopen the app.'))
  });
}

function isLoopbackHostname(hostname) {
  return hostname === '127.0.0.1' || hostname === 'localhost' || hostname === '::1' || hostname === '[::1]';
}

// The resolved target is cached because isTrustedRendererUrl runs on every
// IPC request and the resolution stats the dist build on disk. The cache is
// only valid while backendStartupError is unchanged, so electron-main.js
// calls invalidate() on every transition of that state.
function createRendererResolver({ isPackaged, distIndexPath, devRendererUrl, getBackendStartupError }) {
  let cached = null;

  function resolve() {
    if (!isPackaged && devRendererUrl) {
      return { type: 'url', target: devRendererUrl };
    }
    const startupError = getBackendStartupError();
    if (startupError) {
      return {
        type: 'url',
        target: diagnosticPage({
          accent: '#FF4757',
          heading: 'ESPORTS ISOLATOR PRO',
          message: `Startup safety check failed: ${escapeHtml(startupError)}`
        })
      };
    }
    if (fs.existsSync(distIndexPath)) {
      return { type: 'file', target: distIndexPath };
    }
    return {
      type: 'url',
      target: diagnosticPage({
        accent: '#00D4AA',
        heading: 'ESPORTS ISOLATOR PRO',
        message: 'API bridge is running. React dashboard build is not installed yet.'
      })
    };
  }

  function rendererUrl() {
    if (!cached) {
      cached = resolve();
    }
    return cached;
  }

  function invalidate() {
    cached = null;
  }

  function isTrustedRendererUrl(rawUrl) {
    if (!rawUrl) {
      return false;
    }
    let actual;
    try {
      actual = new URL(rawUrl);
    } catch (_error) {
      return false;
    }

    const expected = rendererUrl();
    if (expected.type === 'file') {
      const expectedFileUrl = new URL(pathToFileURL(expected.target).toString());
      return actual.protocol === 'file:' && actual.pathname === expectedFileUrl.pathname;
    }

    if (!isPackaged && expected.type === 'url') {
      let expectedUrl;
      try {
        expectedUrl = new URL(expected.target);
      } catch (_error) {
        return false;
      }
      if (!['http:', 'https:'].includes(expectedUrl.protocol) || !isLoopbackHostname(expectedUrl.hostname)) {
        return false;
      }
      return actual.origin === expectedUrl.origin;
    }

    return false;
  }

  return { rendererUrl, invalidate, isTrustedRendererUrl };
}

module.exports = {
  createRendererResolver,
  diagnosticPage,
  escapeHtml,
  rendererFailureUrl
};

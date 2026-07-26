import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Build-only CSP for the packaged file:// renderer. Injected at build time so
// dev-mode HMR (which needs the @vite/client script and a ws: connection)
// keeps working. connect-src 'none' is safe because all backend traffic goes
// through the allowlisted IPC bridge, never fetch().
const CSP_CONTENT = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'"
].join('; ');

function injectContentSecurityPolicy() {
  return {
    name: 'inject-content-security-policy',
    apply: 'build',
    transformIndexHtml(html) {
      return {
        html,
        tags: [
          {
            tag: 'meta',
            attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP_CONTENT },
            injectTo: 'head-prepend'
          }
        ]
      };
    }
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), injectContentSecurityPolicy()],
  server: {
    host: '127.0.0.1',
    strictPort: false
  }
});

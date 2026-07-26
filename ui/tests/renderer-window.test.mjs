import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import rendererWindow from '../main/renderer-window.js';

const { createRendererResolver, escapeHtml, rendererFailureUrl } = rendererWindow;

// A file that certainly exists on disk: this test file itself.
const EXISTING_FILE = fileURLToPath(import.meta.url);
const MISSING_FILE = `${EXISTING_FILE}.does-not-exist`;

function packagedResolver(overrides = {}) {
  return createRendererResolver({
    isPackaged: true,
    distIndexPath: EXISTING_FILE,
    devRendererUrl: null,
    getBackendStartupError: () => null,
    ...overrides
  });
}

test('escapeHtml escapes every HTML-sensitive character', () => {
  assert.equal(escapeHtml('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(escapeHtml(42), '42');
});

test('packaged app resolves the dist build and trusts only that file URL', () => {
  const resolver = packagedResolver();
  const target = resolver.rendererUrl();
  assert.deepEqual(target, { type: 'file', target: EXISTING_FILE });

  const trusted = pathToFileURL(EXISTING_FILE).toString();
  assert.equal(resolver.isTrustedRendererUrl(trusted), true);
  assert.equal(resolver.isTrustedRendererUrl(`${trusted}#dashboard`), true);
  assert.equal(resolver.isTrustedRendererUrl(pathToFileURL(MISSING_FILE).toString()), false);
  assert.equal(resolver.isTrustedRendererUrl('http://127.0.0.1:5173/'), false);
  assert.equal(resolver.isTrustedRendererUrl('not a url'), false);
  assert.equal(resolver.isTrustedRendererUrl(''), false);
});

test('dev renderer URL is trusted by origin and only on loopback', () => {
  const resolver = createRendererResolver({
    isPackaged: false,
    distIndexPath: MISSING_FILE,
    devRendererUrl: 'http://127.0.0.1:5173',
    getBackendStartupError: () => null
  });
  assert.deepEqual(resolver.rendererUrl(), { type: 'url', target: 'http://127.0.0.1:5173' });
  assert.equal(resolver.isTrustedRendererUrl('http://127.0.0.1:5173/#dashboard'), true);
  assert.equal(resolver.isTrustedRendererUrl('http://127.0.0.1:4000/'), false);
  assert.equal(resolver.isTrustedRendererUrl('http://evil.example/'), false);

  const nonLoopback = createRendererResolver({
    isPackaged: false,
    distIndexPath: MISSING_FILE,
    devRendererUrl: 'http://evil.example:5173',
    getBackendStartupError: () => null
  });
  assert.equal(nonLoopback.isTrustedRendererUrl('http://evil.example:5173/'), false);
});

test('a backend startup error renders an escaped diagnostic page and is untrusted', () => {
  const resolver = packagedResolver({ getBackendStartupError: () => '<script>alert(1)</script>' });
  const target = resolver.rendererUrl();
  assert.equal(target.type, 'url');
  assert.match(target.target, /^data:text\/html;charset=utf-8,/);
  const html = decodeURIComponent(target.target.slice('data:text/html;charset=utf-8,'.length));
  assert.ok(html.includes('Startup safety check failed'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  // While a diagnostic page is showing, no sender URL may reach the proxy.
  assert.equal(resolver.isTrustedRendererUrl(target.target), false);
});

test('a missing dist build resolves to the API-bridge placeholder page', () => {
  const resolver = packagedResolver({ distIndexPath: MISSING_FILE });
  const target = resolver.rendererUrl();
  assert.equal(target.type, 'url');
  assert.ok(decodeURIComponent(target.target).includes('React dashboard build is not installed yet.'));
});

test('the resolved target is cached until invalidate() is called', () => {
  let error = null;
  let reads = 0;
  const resolver = packagedResolver({
    getBackendStartupError: () => {
      reads += 1;
      return error;
    }
  });
  assert.equal(resolver.rendererUrl().type, 'file');
  assert.equal(resolver.rendererUrl().type, 'file');
  assert.equal(reads, 1);

  error = 'backend integrity check failed';
  // Still cached: the state change is only observed after invalidate().
  assert.equal(resolver.rendererUrl().type, 'file');
  resolver.invalidate();
  const target = resolver.rendererUrl();
  assert.equal(target.type, 'url');
  assert.ok(decodeURIComponent(target.target).includes('backend integrity check failed'));
});

test('rendererFailureUrl escapes the detail and falls back to a default message', () => {
  const url = rendererFailureUrl('<b>boom</b>');
  const html = decodeURIComponent(url.slice('data:text/html;charset=utf-8,'.length));
  assert.ok(html.includes('RENDERER LOAD FAILED'));
  assert.ok(html.includes('&lt;b&gt;boom&lt;/b&gt;'));
  assert.ok(!html.includes('<b>'));
  assert.ok(decodeURIComponent(rendererFailureUrl()).includes('Renderer failed to mount'));
});

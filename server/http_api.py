"""Small stdlib HTTP API for single-user localhost access."""

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .bridge import AdministratorRequired, BridgeConflict
from .config_store import ConfigError

_LOGGER = logging.getLogger("server.http_api")


_GET_ROUTES = {"/status", "/api/status"}
_LIVE_ROUTES = {"/live", "/api/live"}
_TOPOLOGY_ROUTES = {"/topology", "/api/topology"}
_ANALYSIS_ROUTES = {"/analysis", "/api/analysis"}
_READINESS_ROUTES = {"/readiness", "/api/readiness"}
_MSI_ROUTES = {"/msi", "/api/msi"}
_CONFIG_ROUTES = {"/config", "/api/config"}
_CONFIG_DEFAULTS_ROUTES = {"/config/defaults", "/api/config/defaults"}
_LOG_ROUTES = {"/logs", "/api/logs"}
_POST_START_ROUTES = {"/start", "/api/start"}
_POST_STOP_ROUTES = {"/stop", "/api/stop"}
_POST_RECOVER_ROUTES = {"/recover", "/api/recover"}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_MAX_BODY_BYTES = 64 * 1024


class LocalhostThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_loopback_host(host):
    return host in _LOOPBACK_HOSTS


def _allowed_cors_origin(origin):
    if not origin:
        return None
    # FIX 7: do NOT reflect "null"/"file://" origins — sandboxed iframes send
    # Origin: null and could otherwise read responses cross-origin. The Electron
    # renderer loads via file:// but its fetches target http://127.0.0.1 (a
    # genuine loopback http origin), so only loopback http(s) origins are allowed.
    try:
        parsed = urlparse(origin)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme in {"http", "https"} and _is_loopback_host(hostname):
        return origin
    return None


def create_server(address, handler_class):
    host, _port = address
    if not _is_loopback_host(host):
        raise ValueError("API server must bind to localhost, 127.0.0.1, or ::1.")
    return LocalhostThreadingHTTPServer(address, handler_class)


def create_handler(bridge, api_token=None):
    expected_token = str(api_token or "")

    class IsolatorApiHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # A client that declares a Content-Length and stalls must not pin a
        # worker thread forever; a timed-out read surfaces as TimeoutError
        # and the connection is closed quietly.
        timeout = 30

        def log_message(self, _format, *_args):
            # Access logs stay silenced; errors go through log_error below.
            return

        def log_error(self, format, *args):  # noqa: A002 - stdlib signature
            _LOGGER.error("%s - %s", self.address_string(), format % args)

        def _send_cors_headers(self):
            origin = _allowed_cors_origin(self.headers.get("Origin"))
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Isolator-Token")

        def _send_json(self, status_code, payload):
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self._send_cors_headers()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True

        def _send_sse_headers(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self._send_cors_headers()
            self.end_headers()

        def _write_sse_event(self, event_name, payload):
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            frame = f"event: {event_name}\ndata: {data}\n\n".encode("utf-8")
            self.wfile.write(frame)
            self.wfile.flush()

        def _origin_is_cross_site(self):
            # FIX 6: CSRF guard for state-changing routes. A request carrying an
            # Origin header that is NOT an allowed loopback origin is rejected.
            # Requests with no Origin (Electron app, tests, curl) are permitted.
            origin = self.headers.get("Origin")
            if not origin:
                return False
            return _allowed_cors_origin(origin) is None

        def _request_is_authorized(self):
            if not expected_token:
                return True
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], expected_token):
                return True
            token = self.headers.get("X-Isolator-Token", "")
            return bool(token) and secrets.compare_digest(token, expected_token)

        def _reject_unsafe_request(self):
            if self._origin_is_cross_site():
                self._send_json(403, {"ok": False, "error": "forbidden_origin"})
                return True
            if not self._request_is_authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return True
            return False

        def _content_length(self):
            """Parsed Content-Length: 0 when absent, None when malformed."""
            raw = self.headers.get("Content-Length")
            if raw is None:
                return 0
            try:
                length = int(str(raw).strip())
            except ValueError:
                return None
            return length if length >= 0 else None

        def _reject_bad_body(self):
            # BaseHTTPRequestHandler does not decode chunked bodies; accepting
            # the request would silently treat the body as empty, so a PUT
            # /api/config "success" would discard the caller's settings.
            if self.headers.get("Transfer-Encoding"):
                self._send_json(501, {"ok": False, "error": "transfer_encoding_unsupported"})
                return True
            length = self._content_length()
            if length is None:
                self._send_json(400, {"ok": False, "error": "invalid_content_length"})
                return True
            if length > _MAX_BODY_BYTES:
                self._send_json(413, {"ok": False, "error": "body_too_large"})
                return True
            return False

        def _stream_live(self, once=False):
            self._send_sse_headers()
            stream_cancel = threading.Event()
            # live_client() decrements the counter in its finally clause; the
            # try/finally guarantees that runs even if the engine raises here.
            with bridge.live_client():
                try:
                    while True:
                        snapshot = bridge.live_snapshot()
                        self._write_sse_event("snapshot", snapshot)
                        for notification in bridge.notifications_for_snapshot(snapshot):
                            self._write_sse_event("notification", notification)
                        if once:
                            break
                        stream_cancel.wait(bridge.live_interval_seconds(snapshot))
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError):
                    # Client disconnected — propagate so do_GET stays quiet.
                    raise
                except Exception:
                    # An engine exception mid-stream must not kill the worker
                    # thread after headers are sent; log the traceback and end
                    # the stream cleanly so the live_client counter is released.
                    _LOGGER.exception("live stream ended after engine error")
            self.close_connection = True

        def _read_body_bytes(self):
            # _reject_bad_body already capped the declared length, so the
            # loop is bounded; a stalled sender hits the socket timeout.
            length = self._content_length() or 0
            data = b""
            while len(data) < length:
                chunk = self.rfile.read(min(length - len(data), 65536))
                if not chunk:
                    break
                data += chunk
            return data

        def _discard_body(self):
            self._read_body_bytes()

        def _read_json_body(self):
            raw = self._read_body_bytes()
            if not raw:
                return {}
            try:
                return json.loads(
                    raw.decode("utf-8"),
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid numeric constant: {value}")),
                )
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                raise ConfigError([{"field": "$", "message": "Request body must be valid JSON."}]) from exc

        @staticmethod
        def _bool_query(parsed, name):
            return parse_qs(parsed.query).get(name, ["0"])[0] == "1"

        def _run_request(self, handler):
            # One error policy for every verb: client disconnects close
            # quietly, domain errors map to their status codes, and anything
            # unexpected is logged with a traceback plus an opaque id echoed
            # to the client so a user report can be matched to the log.
            try:
                handler()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except ConfigError as exc:
                self._send_json(400, {"ok": False, "error": "invalid_config", "errors": exc.errors})
            except BridgeConflict as exc:
                self._send_json(409, {"ok": False, "error": str(exc)})
            except AdministratorRequired:
                self._send_json(403, {"error": "administrator_required"})
            except Exception as exc:
                error_id = secrets.token_hex(4)
                _LOGGER.exception("unhandled API error id=%s method=%s path=%s", error_id, self.command, self.path)
                self._send_json(500, {"ok": False, "error": type(exc).__name__, "error_id": error_id})

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self._send_cors_headers()
            self.end_headers()
            self.close_connection = True

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if self._reject_unsafe_request():
                return

            def dispatch():
                if path in _GET_ROUTES:
                    self._send_json(200, bridge.status())
                elif path in _CONFIG_DEFAULTS_ROUTES:
                    self._send_json(200, bridge.get_config_defaults())
                elif path in _CONFIG_ROUTES:
                    self._send_json(200, bridge.get_config())
                elif path in _TOPOLOGY_ROUTES:
                    self._send_json(200, bridge.topology(refresh=self._bool_query(parsed, "refresh")))
                elif path in _ANALYSIS_ROUTES:
                    self._send_json(200, bridge.analysis())
                elif path in _READINESS_ROUTES:
                    self._send_json(200, bridge.readiness(refresh=self._bool_query(parsed, "refresh")))
                elif path in _MSI_ROUTES:
                    self._send_json(200, bridge.msi_devices(refresh=self._bool_query(parsed, "refresh")))
                elif path in _LOG_ROUTES:
                    query = parse_qs(parsed.query)
                    self._send_json(200, bridge.logs(limit=query.get("limit", ["500"])[0]))
                elif path in _LIVE_ROUTES:
                    self._stream_live(once=self._bool_query(parsed, "once"))
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})

            self._run_request(dispatch)

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if self._reject_unsafe_request() or self._reject_bad_body():
                return
            self._discard_body()

            def dispatch():
                if path in _POST_START_ROUTES:
                    self._send_json(200, bridge.start())
                elif path in _POST_STOP_ROUTES:
                    self._send_json(200, bridge.stop())
                elif path in _POST_RECOVER_ROUTES:
                    self._send_json(200, bridge.recover())
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})

            self._run_request(dispatch)

        def do_PUT(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if self._reject_unsafe_request() or self._reject_bad_body():
                return
            if path not in _CONFIG_ROUTES:
                self._discard_body()
                self._send_json(404, {"ok": False, "error": "not_found"})
                return

            def dispatch():
                if not self._content_length():
                    # A zero-length PUT used to merge nothing and answer 200,
                    # convincing the caller its settings were saved.
                    raise ConfigError([{"field": "$", "message": "Request body must not be empty."}])
                payload = self._read_json_body()
                if isinstance(payload, dict) and "config" in payload and len(payload) == 1:
                    payload = payload["config"]
                self._send_json(200, bridge.update_config(payload))

            self._run_request(dispatch)

    return IsolatorApiHandler

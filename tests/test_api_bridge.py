import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from isolator.app import EsportsIsolatorPro
from server.__main__ import _parent_heartbeat_loop
from server.__main__ import main as server_main
from server.bridge import AdministratorRequired, BridgeConflict, IsolatorBridge
from server.capability import _TtlCache
from server.http_api import create_handler, create_server

ROOT = Path(__file__).resolve().parents[1]


class RuntimeStatusSnapshotTests(unittest.TestCase):
    def test_runtime_status_is_readonly_and_does_not_enumerate_processes(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._get_processes = lambda: (_ for _ in ()).throw(AssertionError("_get_processes must not run"))

        with isolator._state_lock:
            isolator._active_games[42] = {
                "pid": 42,
                "name": "cs2.exe",
                "tuning_state": "applied",
            }
            isolator._entry_gen += 1
            isolator._touched[42] = {
                "name": "cs2.exe",
                "create_time": 123,
                "state": {},
                "threads": {},
                "source": "optimize_game",
                "gen": isolator._entry_gen,
            }
            isolator._entry_gen += 1
            isolator._touched[77] = {
                "name": "discord.exe",
                "create_time": 456,
                "state": {},
                "threads": {},
                "source": "jail",
                "gen": isolator._entry_gen,
            }
            isolator._active_mutations = 2

        status = isolator.get_runtime_status()

        self.assertTrue(status["game_mode"])
        self.assertEqual([42], status["active_game_pids"])
        self.assertEqual(2, status["tracked_process_count"])
        self.assertEqual(1, status["jailed_process_count"])
        self.assertEqual(2, status["active_mutations"])
        self.assertFalse(status["running"])

    def test_live_snapshot_uses_tracked_processes_without_enumerating_processes(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator._get_processes = lambda: (_ for _ in ()).throw(AssertionError("_get_processes must not run"))

        with isolator._state_lock:
            isolator._active_games[42] = {
                "pid": 42,
                "name": "cs2.exe",
                "tuning_state": "applied",
            }
            isolator._entry_gen += 1
            isolator._touched[42] = {
                "name": "cs2.exe",
                "create_time": 123,
                "state": {
                    "priority_class": 128,
                    "cpu_set_ids": [4, 5, 6, 7],
                    "io_priority": 2,
                    "page_priority": 5,
                    "priority_boost_disabled": True,
                },
                "threads": {1001: {}},
                "source": "optimize_game",
                "gen": isolator._entry_gen,
            }
            isolator._entry_gen += 1
            isolator._touched[77] = {
                "name": "discord.exe",
                "create_time": 456,
                "state": {},
                "threads": {},
                "source": "jail",
                "gen": isolator._entry_gen,
            }

        snapshot = isolator.get_live_snapshot()

        self.assertEqual("tracked_only", snapshot["process_mode"])
        self.assertTrue(snapshot["status"]["game_mode"])
        self.assertEqual(2, snapshot["process_count"])
        by_pid = {process["pid"]: process for process in snapshot["processes"]}
        self.assertEqual("game", by_pid[42]["status"])
        self.assertTrue(by_pid[42]["game"])
        self.assertEqual(1, by_pid[42]["thread_count"])
        self.assertEqual(128, by_pid[42]["priority_class"])
        self.assertEqual([4, 5, 6, 7], by_pid[42]["cpu_set_ids"])
        self.assertEqual(2, by_pid[42]["io_priority"])
        self.assertEqual(5, by_pid[42]["page_priority"])
        self.assertTrue(by_pid[42]["priority_boost_disabled"])
        self.assertEqual("jailed", by_pid[77]["status"])
        self.assertFalse(by_pid[77]["protected"])


class ParentHeartbeatTests(unittest.TestCase):
    def test_parent_heartbeat_requests_shutdown_when_parent_exits(self):
        stop_event = threading.Event()
        shutdown_requested = []
        checks = []

        def fake_parent_alive(parent_pid, _interval_s):
            checks.append(parent_pid)
            return False

        _parent_heartbeat_loop(
            1234,
            stop_event,
            lambda: shutdown_requested.append(True),
            interval_s=0.001,
            is_parent_alive=fake_parent_alive,
        )

        self.assertEqual([1234], checks)
        self.assertEqual([True], shutdown_requested)
        self.assertTrue(stop_event.is_set())


class FakeEngine:
    def __init__(self, run_result=True, recover_result=True):
        self.run_result = run_result
        self.recover_result = recover_result
        self.run_calls = 0
        self.shutdown_calls = 0
        self.recover_calls = 0
        self.running = False
        self.game_mode = False

    def run(self):
        self.run_calls += 1
        self.running = bool(self.run_result)
        return self.run_result

    def shutdown(self):
        self.shutdown_calls += 1
        self.running = False

    def recover(self):
        self.recover_calls += 1
        return self.recover_result

    def get_runtime_status(self):
        return {
            "running": self.running,
            "game_mode": self.game_mode,
            "active_game_pids": [123] if self.game_mode else [],
        }

    def get_live_snapshot(self):
        return {
            "status": self.get_runtime_status(),
            "process_mode": "tracked_only",
            "processes": [],
            "process_count": 0,
        }


class TtlCacheTests(unittest.TestCase):
    def test_serves_fresh_values_expires_on_ttl_and_bypasses_on_refresh(self):
        clock = {"now": 0.0}
        cache = _TtlCache(ttl_s=300, monotonic=lambda: clock["now"])

        self.assertIsNone(cache.get())
        cache.set({"ok": True})
        clock["now"] = 299.0
        self.assertEqual({"ok": True}, cache.get())
        self.assertIsNone(cache.get(refresh=True))
        clock["now"] = 300.0
        self.assertIsNone(cache.get())

    def test_clear_empties_the_cached_value(self):
        cache = _TtlCache(ttl_s=300, monotonic=lambda: 0.0)
        cache.set({"ok": True})

        cache.clear()

        self.assertIsNone(cache.get())


class BridgeLifecycleTests(unittest.TestCase):
    def test_stopped_status_keys_match_engine_runtime_status(self):
        engine = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        engine_status = engine.get_runtime_status()

        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = IsolatorBridge(
                config_path=str(Path(tmpdir) / "config.json"),
                engine_factory=lambda *_args: FakeEngine(),
                admin_check=lambda: True,
            )
            stopped = bridge._stopped_status()
            bridge._engine = engine
            running = bridge.status()

        # The engine itself does not report "config"; the bridge merges the
        # persisted toggles into BOTH branches, so bridge.status() has full
        # key parity whether or not an engine is attached.
        self.assertEqual(set(engine_status) | {"config"}, set(stopped))
        self.assertEqual(set(stopped), set(running))
        self.assertEqual(set(engine_status["api"]), set(stopped["api"]))

    def test_running_status_includes_persisted_config_toggles(self):
        # The Dashboard reads status.config.* for the power/timer indicators;
        # they must stay defined while the engine is running, and the bridge
        # must merge into a copy rather than mutate the engine's status dict.
        class StickyStatusEngine(FakeEngine):
            def get_runtime_status(self):
                if not hasattr(self, "_status"):
                    self._status = super().get_runtime_status()
                return self._status

        engine = StickyStatusEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = IsolatorBridge(
                config_path=str(Path(tmpdir) / "config.json"),
                engine_factory=lambda *_args: engine,
                admin_check=lambda: True,
            )
            bridge.start()

            status = bridge.status()

        self.assertTrue(status["running"])
        self.assertEqual(bridge._status_config, status["config"])
        self.assertIn("disable_power_scheme_switch", status["config"])
        self.assertIn("disable_timer_resolution_tweak", status["config"])
        self.assertNotIn("config", engine.get_runtime_status())

    def test_stopped_status_keeps_the_complete_runtime_schema(self):
        bridge = IsolatorBridge(admin_check=lambda: True)

        status = bridge.status()

        self.assertFalse(status["monitoring_active"])
        self.assertEqual([], status["active_games"])
        self.assertEqual([], status["active_game_pids"])
        self.assertEqual([], status["capability_issues"])
        self.assertEqual([], status["discovery_issues"])

    def test_start_stop_status_use_single_engine_instance(self):
        created = []

        def factory(config_path, scan_game_libraries):
            engine = FakeEngine()
            created.append((config_path, scan_game_libraries, engine))
            return engine

        bridge = IsolatorBridge(config_path="config.json", engine_factory=factory, admin_check=lambda: True)

        start = bridge.start()
        second_start = bridge.start()
        status = bridge.status()
        stop = bridge.stop()

        self.assertTrue(start["ok"])
        self.assertTrue(second_start["already_running"])
        self.assertTrue(status["running"])
        self.assertFalse(stop["status"]["running"])
        self.assertEqual(1, len(created))
        self.assertEqual(("config.json", True), created[0][:2])
        self.assertEqual(1, created[0][2].run_calls)
        self.assertEqual(1, created[0][2].shutdown_calls)

    def test_recover_uses_short_lived_engine_and_is_blocked_while_running(self):
        created = []

        def factory(config_path, scan_game_libraries):
            engine = FakeEngine()
            created.append((config_path, scan_game_libraries, engine))
            return engine

        bridge = IsolatorBridge(config_path="custom.json", engine_factory=factory, admin_check=lambda: True)

        recover = bridge.recover()
        bridge.start()

        with self.assertRaises(BridgeConflict):
            bridge.recover()

        self.assertTrue(recover["ok"])
        self.assertEqual(("custom.json", False), created[0][:2])
        self.assertEqual(1, created[0][2].recover_calls)

    def test_privileged_lifecycle_refuses_before_engine_creation(self):
        created = []
        bridge = IsolatorBridge(
            engine_factory=lambda *_args: created.append(FakeEngine()) or created[-1],
            admin_check=lambda: False,
        )

        with self.assertRaises(AdministratorRequired):
            bridge.start()
        with self.assertRaises(AdministratorRequired):
            bridge.recover()

        self.assertEqual([], created)

    def test_live_snapshot_tracks_connected_clients(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())

        self.assertEqual(0, bridge.live_client_count())

        with bridge.live_client():
            snapshot = bridge.live_snapshot()
            self.assertEqual(1, bridge.live_client_count())

        self.assertEqual(0, bridge.live_client_count())
        self.assertEqual(1, snapshot["api"]["live_clients"])
        self.assertTrue(snapshot["api"]["lazy_push"])


class HttpApiTests(unittest.TestCase):
    def test_start_and_recover_return_administrator_required_without_creating_engine(self):
        created = []
        bridge = IsolatorBridge(
            engine_factory=lambda *_args: created.append(FakeEngine()) or created[-1],
            admin_check=lambda: False,
        )
        server = create_server(("127.0.0.1", 0), create_handler(bridge, api_token="secret-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        responses = []
        try:
            for path in ("/api/start", "/api/recover"):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                conn.request("POST", path, headers={"Authorization": "Bearer secret-token"})
                response = conn.getresponse()
                responses.append((response.status, json.loads(response.read().decode("utf-8"))))
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual([(403, {"error": "administrator_required"})] * 2, responses)
        self.assertEqual([], created)

    def test_status_endpoint_returns_json_and_dev_cors(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            conn.request("GET", "/api/status", headers={"Origin": "http://localhost:5173"})
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        finally:
            if conn is not None:
                conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(200, response.status)
        self.assertEqual("application/json", response.getheader("Content-Type"))
        self.assertEqual("http://localhost:5173", response.getheader("Access-Control-Allow-Origin"))
        self.assertFalse(body["running"])
        self.assertEqual("idle", body["api"]["live_updates"])

    def test_live_endpoint_is_lazy_and_streams_one_sse_snapshot(self):
        class CountingBridge(IsolatorBridge):
            def __init__(self):
                super().__init__(engine_factory=lambda *_args: FakeEngine())
                self.snapshot_calls = 0

            def live_snapshot(self):
                self.snapshot_calls += 1
                snapshot = super().live_snapshot()
                snapshot["test_sequence"] = self.snapshot_calls
                return snapshot

        bridge = CountingBridge()
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = None
        try:
            self.assertEqual(0, bridge.snapshot_calls)
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            conn.request("GET", "/api/live?once=1", headers={"Origin": "http://localhost:5173"})
            response = conn.getresponse()
            body = response.read().decode("utf-8")
        finally:
            if conn is not None:
                conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(200, response.status)
        self.assertEqual("text/event-stream", response.getheader("Content-Type"))
        self.assertIn("event: snapshot\n", body)
        self.assertIn('"test_sequence":1', body)
        self.assertEqual(1, bridge.snapshot_calls)
        self.assertEqual(0, bridge.live_client_count())

    def test_live_endpoint_treats_connection_aborted_as_client_disconnect(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        handler_class = create_handler(bridge)

        def aborting_write(_handler, _event_name, _payload):
            raise ConnectionAbortedError("client closed")

        handler_class._write_sse_event = aborting_write
        server = create_server(("127.0.0.1", 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        stderr = io.StringIO()
        conn = None
        with contextlib.redirect_stderr(stderr):
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                conn.request("GET", "/api/live?once=1")
                response = conn.getresponse()
                response.read()
            finally:
                if conn is not None:
                    conn.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(200, response.status)
        self.assertEqual(0, bridge.live_client_count())
        self.assertNotIn("ConnectionAbortedError", stderr.getvalue())

    def test_lifecycle_post_treats_connection_aborted_as_client_disconnect(self):
        bridge = IsolatorBridge(
            engine_factory=lambda *_args: FakeEngine(),
            admin_check=lambda: True,
        )
        handler_class = create_handler(bridge)

        def aborting_send(_handler, _status, _payload):
            raise ConnectionAbortedError("client closed")

        handler_class._send_json = aborting_send
        server = create_server(("127.0.0.1", 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        stderr = io.StringIO()
        conn = None
        with contextlib.redirect_stderr(stderr):
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                conn.request("POST", "/api/start")
                with self.assertRaises(http.client.RemoteDisconnected):
                    conn.getresponse()
            finally:
                if conn is not None:
                    conn.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertNotIn("ConnectionAbortedError", stderr.getvalue())

    def test_config_put_treats_connection_aborted_as_client_disconnect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = IsolatorBridge(
                config_path=str(Path(tmpdir) / "config.json"),
                engine_factory=lambda *_args: FakeEngine(),
            )
            handler_class = create_handler(bridge)

            def aborting_send(_handler, _status, _payload):
                raise ConnectionAbortedError("client closed")

            handler_class._send_json = aborting_send
            server = create_server(("127.0.0.1", 0), handler_class)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            stderr = io.StringIO()
            conn = None
            with contextlib.redirect_stderr(stderr):
                thread.start()
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    conn.request("PUT", "/api/config", body='{"enable_background_jailing": true}')
                    with self.assertRaises(http.client.RemoteDisconnected):
                        conn.getresponse()
                finally:
                    if conn is not None:
                        conn.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

        self.assertNotIn("ConnectionAbortedError", stderr.getvalue())

    def _request_status(self, method, path, body=None, headers=None):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            if conn is not None:
                conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_chunked_transfer_encoding_is_rejected_with_501(self):
        # No body on purpose: the server rejects on the header alone before
        # reading, and racing a body write against the early 501 close makes
        # the client side flaky under load.
        status, payload = self._request_status(
            "PUT",
            "/api/config",
            headers={"Transfer-Encoding": "chunked"},
        )

        self.assertEqual(501, status)
        self.assertEqual("transfer_encoding_unsupported", payload["error"])

    def test_malformed_content_length_is_rejected_with_400(self):
        status, payload = self._request_status(
            "POST", "/api/stop", headers={"Content-Length": "banana"}
        )

        self.assertEqual(400, status)
        self.assertEqual("invalid_content_length", payload["error"])

    def test_oversized_declared_body_is_rejected_with_413(self):
        status, payload = self._request_status(
            "POST", "/api/stop", headers={"Content-Length": str(70 * 1024)}
        )

        self.assertEqual(413, status)
        self.assertEqual("body_too_large", payload["error"])

    def test_empty_config_put_is_rejected_instead_of_silently_succeeding(self):
        status, payload = self._request_status("PUT", "/api/config")

        self.assertEqual(400, status)
        self.assertEqual("invalid_config", payload["error"])

    def test_unhandled_engine_error_returns_error_id_and_logs_traceback(self):
        class ExplodingEngine:
            def get_runtime_status(self):
                raise RuntimeError("engine exploded")

        bridge = IsolatorBridge(engine_factory=lambda *_args: ExplodingEngine())
        bridge._engine = ExplodingEngine()
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = None
        try:
            with self.assertLogs("server.http_api", level="ERROR") as captured:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                conn.request("GET", "/api/status")
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            if conn is not None:
                conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(500, response.status)
        self.assertEqual("RuntimeError", payload["error"])
        self.assertTrue(payload["error_id"])
        joined = "\n".join(captured.output)
        self.assertIn(payload["error_id"], joined)
        self.assertIn("engine exploded", joined)

    def test_live_stream_uses_cancellable_wait_instead_of_sleep(self):
        source = (ROOT / "server" / "http_api.py").read_text(encoding="utf-8")

        self.assertIn("threading.Event", source)
        self.assertIn(".wait(bridge.live_interval_seconds(snapshot))", source)
        self.assertNotIn("time.sleep", source)

    def test_token_protects_config_logs_and_lifecycle_routes(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        server = create_server(("127.0.0.1", 0), create_handler(bridge, api_token="secret-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            unauthorized_routes = [
                ("GET", "/api/status", None),
                ("GET", "/api/config", None),
                ("GET", "/api/config/defaults", None),
                ("GET", "/api/logs", None),
                ("GET", "/api/live?once=1", None),
                ("GET", "/api/topology?refresh=1", None),
                ("GET", "/api/analysis", None),
                ("GET", "/api/readiness", None),
                ("GET", "/api/msi", None),
                ("POST", "/api/start", b""),
                ("POST", "/api/stop", b""),
                ("POST", "/api/recover", b""),
                ("PUT", "/api/config", b"{}"),
            ]
            unauthorized = []
            for method, path, body in unauthorized_routes:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                conn.request(method, path, body=body)
                response = conn.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                unauthorized.append((response.status, payload["error"]))
                conn.close()

            authorized = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            authorized.request("GET", "/api/status", headers={"Authorization": "Bearer secret-token"})
            ok_response = authorized.getresponse()
            ok_body = json.loads(ok_response.read().decode("utf-8"))
            authorized.close()

            header_token = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            header_token.request("GET", "/api/status", headers={"X-Isolator-Token": "secret-token"})
            header_response = header_token.getresponse()
            header_response.read()
            header_token.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(all(status == 401 and error == "unauthorized" for status, error in unauthorized))
        self.assertEqual(200, ok_response.status)
        self.assertEqual(200, header_response.status)
        self.assertFalse(ok_body["running"])

    def test_standalone_server_requires_token_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as ctx:
                    server_main(["--port", "0"])

        self.assertEqual(2, ctx.exception.code)
        self.assertIn("--api-token", stderr.getvalue())

    def test_standalone_server_refuses_non_elevated_process_before_bridge_or_bind(self):
        with patch("server.__main__.is_process_elevated", return_value=False), patch(
            "server.__main__.IsolatorBridge"
        ) as bridge_cls, patch("server.__main__.create_server") as create_server_mock:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as ctx:
                    server_main(["--port", "0", "--api-token", "secret-token"])

        self.assertEqual(5, ctx.exception.code)
        self.assertIn("administrator_required", stderr.getvalue())
        bridge_cls.assert_not_called()
        create_server_mock.assert_not_called()

    def test_malformed_origin_is_rejected_without_crashing(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        server = create_server(("127.0.0.1", 0), create_handler(bridge, api_token="secret-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            conn.request("GET", "/api/status", headers={"Origin": "http://[::1", "Authorization": "Bearer secret-token"})
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(403, response.status)
        self.assertEqual("forbidden_origin", payload["error"])

    def test_cross_origin_post_is_rejected_before_large_body_is_read(self):
        bridge = IsolatorBridge(engine_factory=lambda *_args: FakeEngine())
        server = create_server(("127.0.0.1", 0), create_handler(bridge, api_token="secret-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            conn.request(
                "POST",
                "/api/start",
                body=None,
                headers={
                    "Origin": "https://attacker.example",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(70 * 1024),
                },
            )
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(403, response.status)
        self.assertEqual("forbidden_origin", payload["error"])


if __name__ == "__main__":
    unittest.main()

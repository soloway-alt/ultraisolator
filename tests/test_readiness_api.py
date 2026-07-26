import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from server.bridge import IsolatorBridge
from server.http_api import create_handler, create_server
from server.readiness import build_readiness_payload


class FakeReadinessEngine:
    def __init__(self, status, topology):
        self._status = status
        self._topology = topology
        self.topology_calls = 0

    def get_runtime_status(self):
        return self._status

    def get_topology_snapshot(self, refresh=False):
        self.topology_calls += 1
        if refresh:
            raise AssertionError("readiness must not refresh topology")
        return self._topology


class ReadinessApiTests(unittest.TestCase):
    def test_capability_check_uses_structured_severity_with_legacy_fallback(self):
        cases = [
            (
                {
                    "capability_issues": [{
                        "code": "steam_auto_detection_enabled",
                        "severity": "info",
                        "data": {},
                        "message": "Steam auto-detection enabled.",
                    }],
                    "capability_notes": ["Steam auto-detection enabled."],
                },
                "ok",
            ),
            (
                {
                    "capability_issues": [{
                        "code": "cpu_topology_unavailable",
                        "severity": "warning",
                        "data": {},
                        "message": "CPU topology is unavailable.",
                    }],
                    "capability_notes": [],
                },
                "warning",
            ),
            ({"capability_issues": [], "capability_notes": ["Legacy warning."]}, "warning"),
        ]

        for status, expected in cases:
            with self.subTest(expected=expected, status=status):
                payload = build_readiness_payload(status, {}, {})
                check = next(item for item in payload["checks"] if item["id"] == "capability_notes")
                self.assertEqual(expected, check["status"])

    def _request_json(self, server, path):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            conn.close()

    def _serve_bridge(self, bridge):
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_readiness_endpoint_returns_cached_checklist(self):
        status = {
            "running": True,
            "game_mode": False,
            "admin": True,
            "timer_resolution_applied": 156250,
            "power_plan_active": True,
            "power_scheme_in_use": "Ultimate Performance",
            "capability_notes": [],
            "topology_available": True,
            "persistent_recovery_incomplete": False,
            "reported_failure_count": 0,
        }
        topology = {
            "available": True,
            "summary": {"core_count": 8, "logical_processor_count": 16},
            "partitions": {
                "game": {"core_count": 4},
                "background": {"core_count": 2},
                "housekeeping": {"core_count": 2},
            },
        }
        config = {
            "enable_background_jailing": True,
            "disable_timer_resolution_tweak": False,
            "disable_power_scheme_switch": False,
            "disable_game_priority_boost": False,
            "anti_cheat_mode": "aggressive",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            engine = FakeReadinessEngine(status, topology)
            bridge = IsolatorBridge(config_path=str(config_path), engine_factory=lambda *_args: engine)
            bridge._engine = engine
            server, thread = self._serve_bridge(bridge)
            try:
                status_code, payload = self._request_json(server, "/api/readiness")
                second_status_code, second_payload = self._request_json(server, "/api/readiness")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(200, status_code)
        self.assertEqual(200, second_status_code)
        self.assertTrue(payload["available"])
        self.assertTrue(second_payload["cache"]["hit"])
        self.assertEqual(1, engine.topology_calls)
        self.assertGreaterEqual(payload["summary"]["ok"], 5)
        self.assertTrue(any(check["id"] == "power_plan" and check["status"] == "ok" for check in payload["checks"]))
        self.assertTrue(any(check["id"] == "background_jailing" and check["status"] == "ok" for check in payload["checks"]))

    def test_config_update_invalidates_cached_readiness(self):
        status = {
            "running": True,
            "game_mode": False,
            "admin": True,
            "timer_resolution_applied": 156250,
            "power_plan_active": True,
            "power_scheme_in_use": "Ultimate Performance",
            "capability_notes": [],
            "topology_available": True,
            "persistent_recovery_incomplete": False,
            "reported_failure_count": 0,
        }
        topology = {
            "available": True,
            "summary": {"core_count": 8, "logical_processor_count": 16},
            "partitions": {
                "game": {"core_count": 4},
                "background": {"core_count": 2},
                "housekeeping": {"core_count": 2},
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"enable_background_jailing": True}), encoding="utf-8")
            engine = FakeReadinessEngine(status, topology)
            bridge = IsolatorBridge(config_path=str(config_path), engine_factory=lambda *_args: engine)
            bridge._engine = engine
            server, thread = self._serve_bridge(bridge)
            try:
                _status_code, seeded = self._request_json(server, "/api/readiness")
                bridge.update_config({"enable_background_jailing": False})
                _status_code, updated = self._request_json(server, "/api/readiness")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        seeded_check = next(check for check in seeded["checks"] if check["id"] == "background_jailing")
        updated_check = next(check for check in updated["checks"] if check["id"] == "background_jailing")
        self.assertEqual("ok", seeded_check["status"])
        self.assertEqual("warning", updated_check["status"])
        self.assertFalse(updated["cache"]["hit"])

    def test_readiness_endpoint_pauses_in_game_mode_without_topology_read(self):
        status = {
            "running": True,
            "game_mode": True,
            "admin": True,
            "timer_resolution_applied": 156250,
            "power_plan_active": True,
            "power_scheme_in_use": "Ultimate Performance",
        }
        engine = FakeReadinessEngine(status, {"available": True})
        bridge = IsolatorBridge(config_path="config.json", engine_factory=lambda *_args: engine)
        bridge._engine = engine
        server, thread = self._serve_bridge(bridge)
        try:
            status_code, payload = self._request_json(server, "/api/readiness")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(200, status_code)
        self.assertFalse(payload["available"])
        self.assertEqual("paused_in_game_mode", payload["reason"])
        self.assertEqual(0, engine.topology_calls)


if __name__ == "__main__":
    unittest.main()

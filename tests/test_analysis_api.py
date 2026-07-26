import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from server.analysis import build_analysis_payload
from server.bridge import IsolatorBridge
from server.http_api import create_handler, create_server


class FakeAnalysisEngine:
    def __init__(self, status, topology):
        self._status = status
        self._topology = topology
        self.topology_calls = 0

    def get_runtime_status(self):
        return self._status

    def get_topology_snapshot(self, refresh=False):
        self.topology_calls += 1
        if refresh:
            raise AssertionError("analysis must not refresh topology")
        return self._topology


class AnalysisApiTests(unittest.TestCase):
    def test_capability_score_uses_structured_severity_with_legacy_fallback(self):
        cases = [
            (
                {
                    "capability_issues": [{
                        "code": "epic_auto_detection_enabled",
                        "severity": "info",
                        "data": {},
                        "message": "Epic Games auto-detection enabled.",
                    }],
                    "capability_notes": ["Epic Games auto-detection enabled."],
                },
                "ok",
            ),
            (
                {
                    "capability_issues": [{
                        "code": "ifeo_write_denied",
                        "severity": "error",
                        "data": {},
                        "message": "Access denied.",
                    }],
                    "capability_notes": [],
                },
                "warning",
            ),
            ({"capability_issues": [], "capability_notes": ["Legacy warning."]}, "warning"),
        ]

        for status, expected in cases:
            with self.subTest(expected=expected, status=status):
                payload = build_analysis_payload(status, {}, {})
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

    def test_analysis_endpoint_returns_score_and_checklist(self):
        status = {
            "running": True,
            "game_mode": False,
            "admin": True,
            "background_jailing": True,
            "power_plan_active": False,
            "power_scheme_in_use": None,
            "timer_resolution_applied": 5000,
            "persistent_recovery_incomplete": False,
            "reported_failure_count": 0,
            "capability_notes": [],
            "cpu_partitions": {
                "game": 4,
                "background": 2,
                "housekeeping": 1,
                "game_cores": 1,
            },
            "topology_available": True,
            "disable_game_priority_boost": False,
            "disable_power_scheme_switch": False,
            "disable_timer_resolution_tweak": False,
            "api": {"live_updates": "idle"},
        }
        topology = {
            "available": True,
            "summary": {
                "logical_processor_count": 8,
                "core_count": 4,
                "llc_group_count": 2,
                "heterogeneous_efficiency": True,
                "multi_llc": True,
                "last_refresh_monotonic_s": 123.4,
            },
            "cores": [],
            "llc_groups": [],
            "cpu_sets": [],
            "partitions": {
                "game": {"label": "Game", "cpu_set_ids": [0, 1, 2, 3], "logical_processor_count": 4, "core_ids": ["c0"], "core_count": 1},
                "background": {"label": "Background", "cpu_set_ids": [4, 5], "logical_processor_count": 2, "core_ids": ["c1"], "core_count": 1},
                "housekeeping": {"label": "Housekeeping", "cpu_set_ids": [6], "logical_processor_count": 1, "core_ids": ["c2"], "core_count": 1},
            },
        }
        config = {
            "enable_background_jailing": True,
            "disable_timer_resolution_tweak": False,
            "disable_game_priority_boost": False,
            "disable_power_scheme_switch": False,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            bridge = IsolatorBridge(
                config_path=str(config_path),
                engine_factory=lambda *_args: FakeAnalysisEngine(status, topology),
            )
            bridge._engine = FakeAnalysisEngine(status, topology)
            server, thread = self._serve_bridge(bridge)
            try:
                status_code, payload = self._request_json(server, "/api/analysis")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(200, status_code)
        self.assertTrue(payload["available"])
        self.assertEqual("analysis", payload["mode"])
        self.assertEqual(100, payload["score"])
        self.assertEqual("excellent", payload["grade"])
        self.assertIn("start ready", payload["summary"].lower())
        self.assertIn("CPU isolation", payload["categories"])
        self.assertNotIn("boost_potential", payload)
        self.assertNotIn("bottleneck", payload)
        self.assertEqual(0, payload["analysis_calls"]["topology_refreshes"])
        self.assertTrue(any(check["id"] == "admin" and check["status"] == "ok" for check in payload["checks"]))
        self.assertTrue(any(check["id"] == "cpu_topology" and check["status"] == "ok" for check in payload["checks"]))

    def test_analysis_endpoint_pauses_in_game_mode_without_refreshing_topology(self):
        status = {
            "running": True,
            "game_mode": True,
            "admin": True,
            "background_jailing": True,
            "power_plan_active": True,
            "power_scheme_in_use": "ultimate",
            "timer_resolution_applied": 5000,
            "persistent_recovery_incomplete": False,
            "reported_failure_count": 0,
            "capability_notes": [],
            "cpu_partitions": {"game": 4, "background": 2, "housekeeping": 1, "game_cores": 1},
            "topology_available": True,
            "disable_game_priority_boost": False,
            "disable_power_scheme_switch": False,
            "disable_timer_resolution_tweak": False,
            "api": {"live_updates": "paused"},
        }
        topology = {
            "available": True,
            "summary": {},
            "cores": [],
            "llc_groups": [],
            "cpu_sets": [],
            "partitions": {},
        }
        engine = FakeAnalysisEngine(status, topology)
        bridge = IsolatorBridge(config_path="config.json", engine_factory=lambda *_args: engine)
        bridge._engine = engine
        server, thread = self._serve_bridge(bridge)
        try:
            status_code, payload = self._request_json(server, "/api/analysis")
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

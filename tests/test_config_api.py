import http.client
import json
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path

from isolator.app import EsportsIsolatorPro
from server.bridge import IsolatorBridge
from server.config_store import DEFAULT_CONFIG, ConfigError, ConfigStore
from server.http_api import create_handler, create_server


class ConfigStoreTests(unittest.TestCase):
    def test_defaults_include_runtime_constraints_and_reload_policy(self):
        store = ConfigStore("__missing_config__.json")

        defaults = store.defaults_response()

        self.assertEqual(["cs2.exe", "valorant.exe"], defaults["defaults"]["games"][:2])
        self.assertEqual([], defaults["defaults"]["app_profiles"])
        self.assertEqual("app_profiles", defaults["schema"]["app_profiles"]["type"])
        self.assertEqual(["idle", "below_normal", "normal", "above_normal", "high"], defaults["schema"]["app_profiles"]["priority_choices"])
        self.assertEqual(50, defaults["schema"]["poll_interval_active_ms"]["min"])
        self.assertEqual(30000, defaults["schema"]["poll_interval_active_ms"]["max"])
        self.assertEqual(5000, defaults["schema"]["maintenance_jail_interval_ms"]["min"])
        self.assertEqual(300000, defaults["schema"]["maintenance_jail_interval_ms"]["max"])
        self.assertEqual(["aggressive", "conservative"], defaults["schema"]["anti_cheat_mode"]["choices"])
        self.assertEqual([], defaults["reload"]["hot_reloadable"])
        self.assertTrue(defaults["reload"]["restart_required_when_running"])

    def test_config_example_matches_runtime_defaults(self):
        example = json.loads((Path(__file__).resolve().parents[1] / "config.json.example").read_text(encoding="utf-8"))

        self.assertEqual(DEFAULT_CONFIG, example)

    def test_update_coerces_numeric_values_and_writes_canonical_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            store = ConfigStore(str(config_path))

            result = store.update({"games": ["cs2"], "poll_interval_active_ms": "5000"}, running=False)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertFalse(result["restart_required"])
            self.assertEqual(["cs2.exe"], result["config"]["games"])
            self.assertEqual(5000, saved["poll_interval_active_ms"])
            self.assertEqual("cs2.exe", saved["games"][0])

    def test_partial_update_preserves_existing_persisted_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({
                "games": ["custom.exe"],
                "protected_extra": ["keepme.exe"],
                "app_profiles": [{"exe": "obs.exe", "never_jail": True}],
                "log_file": "logs/session.log",
            }), encoding="utf-8")
            store = ConfigStore(str(config_path))

            result = store.update({"enable_background_jailing": True}, running=False)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(result["config"]["enable_background_jailing"])
            self.assertEqual(["custom.exe"], saved["games"])
            self.assertEqual(["keepme.exe"], saved["protected_extra"])
            self.assertEqual("obs.exe", saved["app_profiles"][0]["exe"])
            self.assertEqual(
                os.path.normcase(os.path.realpath(str(Path(tmpdir) / "logs" / "session.log"))),
                os.path.normcase(os.path.realpath(saved["log_file"])),
            )

    def test_removed_legacy_keys_stay_loadable_and_are_dropped_on_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({
                "games": ["custom.exe"],
                "enable_hot_thread_tuning": True,
                "hot_thread_limit": 8,
                "hot_thread_refresh_ms": 500,
                "thread_sample_window_ms": 100,
            }), encoding="utf-8")
            store = ConfigStore(str(config_path))

            loaded = store.read()
            self.assertEqual(["custom.exe"], loaded["config"]["games"])
            self.assertNotIn("enable_hot_thread_tuning", loaded["config"])

            store.update({"enable_background_jailing": True}, running=False)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(["custom.exe"], saved["games"])
            for legacy_key in ("enable_hot_thread_tuning", "hot_thread_limit", "hot_thread_refresh_ms", "thread_sample_window_ms"):
                self.assertNotIn(legacy_key, saved)

    def test_concurrent_updates_preserve_every_field_and_the_file_stays_valid(self):
        updates = {
            "housekeeping_cores": 2,
            "poll_interval_idle_ms": 1500,
            "poll_interval_active_ms": 2500,
            "maintenance_jail_batch_size": 6,
            "maintenance_jail_interval_ms": 31000,
            "maintenance_jail_batch_cooldown_ms": 6000,
            "game_close_debounce_s": 4,
            "game_exit_restore_delay_s": 11,
            "gc_full_collect_interval_s": 1900,
            "maintenance_skip_after_quiet_cycles": 4,
            "enable_background_jailing": True,
            "disable_timer_resolution_tweak": True,
            "disable_game_priority_boost": True,
            "disable_power_scheme_switch": True,
            "auto_detect_steam_games": False,
            "auto_detect_epic_games": False,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            store = ConfigStore(str(config_path))
            barrier = threading.Barrier(len(updates))
            errors = []

            def apply_update(field, value):
                try:
                    barrier.wait(timeout=10)
                    store.update({field: value}, running=False)
                except Exception as exc:  # noqa: BLE001 - collected for assertion
                    errors.append((field, exc))

            threads = [
                threading.Thread(target=apply_update, args=(field, value))
                for field, value in updates.items()
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            self.assertEqual([], errors)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            for field, value in updates.items():
                self.assertEqual(value, saved[field], f"lost concurrent update for {field}")

    def test_relative_log_file_is_canonicalized_under_config_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "config.json"
            store = ConfigStore(str(config_path))

            result = store.update({"log_file": "logs/session.log"}, running=False)

            self.assertEqual(
                os.path.normcase(os.path.realpath(str(config_path.parent / "logs" / "session.log"))),
                os.path.normcase(os.path.realpath(result["config"]["log_file"])),
            )

    def test_integer_fields_reject_json_floats(self):
        store = ConfigStore("__missing_config__.json")

        with self.assertRaises(ConfigError) as ctx:
            store.update({"poll_interval_active_ms": 50.9, "housekeeping_cores": 1.9}, running=False)

        fields = {error["field"] for error in ctx.exception.errors}
        self.assertIn("poll_interval_active_ms", fields)
        self.assertIn("housekeeping_cores", fields)

    def test_numeric_fields_reject_values_above_safe_maximums(self):
        store = ConfigStore("__missing_config__.json")
        maximums = {
            "housekeeping_cores": 16,
            "poll_interval_idle_ms": 60000,
            "poll_interval_active_ms": 30000,
            "maintenance_jail_batch_size": 64,
            "maintenance_jail_interval_ms": 300000,
            "maintenance_jail_batch_cooldown_ms": 60000,
            "game_close_debounce_s": 60,
            "game_exit_restore_delay_s": 300,
            "gc_full_collect_interval_s": 86400,
            "maintenance_skip_after_quiet_cycles": 100,
        }

        schema = store.defaults_response()["schema"]
        for field, maximum in maximums.items():
            self.assertEqual(maximum, schema[field]["max"])
            self.assertEqual(maximum, store.validate({field: maximum}, partial=True)[field])

        with self.assertRaises(ConfigError) as ctx:
            store.update({field: maximum + 1 for field, maximum in maximums.items()}, running=False)

        errors = {error["field"]: error["message"] for error in ctx.exception.errors}
        self.assertEqual(set(maximums), set(errors))
        for field, maximum in maximums.items():
            self.assertIn(f"must be <= {maximum}", errors[field])

    def test_float_fields_reject_non_finite_values(self):
        store = ConfigStore("__missing_config__.json")

        with self.assertRaises(ConfigError) as ctx:
            store.update({"game_exit_restore_delay_s": math.inf}, running=False)

        self.assertEqual("game_exit_restore_delay_s", ctx.exception.errors[0]["field"])

    def test_app_profile_normalization_matches_engine_duplicate_rules(self):
        store = ConfigStore("__missing_config__.json")

        with self.assertRaises(ConfigError) as ctx:
            store.update({"app_profiles": [{"exe": "foo.exe"}, {"exe": "foo.exe."}, {"exe": "bar.exe.exe"}]}, running=False)

        self.assertIn("Duplicate profile executable: foo.exe.", [error["message"] for error in ctx.exception.errors])

    def test_update_rejects_invalid_values_with_field_errors(self):
        store = ConfigStore("__missing_config__.json")

        with self.assertRaises(ConfigError) as ctx:
            store.update({
                "games": "cs2.exe",
                "poll_interval_active_ms": 10,
                "anti_cheat_mode": "paranoid",
            }, running=False)

        fields = {error["field"] for error in ctx.exception.errors}
        self.assertIn("games", fields)
        self.assertIn("poll_interval_active_ms", fields)
        self.assertIn("anti_cheat_mode", fields)

    def test_update_normalizes_app_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            store = ConfigStore(str(config_path))

            result = store.update({
                "app_profiles": [
                    {
                        "exe": "Discord",
                        "enabled": True,
                        "treat_as_game": True,
                        "never_jail": False,
                        "always_jail": False,
                        "priority_class": "High",
                    }
                ]
            }, running=False)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [{
                    "exe": "discord.exe",
                    "enabled": True,
                    "treat_as_game": True,
                    "never_jail": False,
                    "always_jail": False,
                    "priority_class": "high",
                }],
                result["config"]["app_profiles"],
            )
            self.assertEqual(result["config"]["app_profiles"], saved["app_profiles"])

    def test_update_rejects_invalid_app_profiles(self):
        store = ConfigStore("__missing_config__.json")

        with self.assertRaises(ConfigError) as ctx:
            store.update({
                "app_profiles": [
                    {"exe": "", "priority_class": "realtime"},
                    {"exe": "tool.exe", "never_jail": True, "always_jail": True},
                ]
            }, running=False)

        fields = {error["field"] for error in ctx.exception.errors}
        self.assertIn("app_profiles[0].exe", fields)
        self.assertIn("app_profiles[0].priority_class", fields)
        self.assertIn("app_profiles[1]", fields)

    def test_engine_fails_closed_on_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"log_file": str(Path(tmpdir).parent / "escape.log")}), encoding="utf-8")

            with self.assertRaises(ConfigError):
                EsportsIsolatorPro(config_path=str(config_path), scan_game_libraries=False)

    def test_set_log_file_rejects_paths_outside_config_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            isolator = EsportsIsolatorPro(config_path=str(config_path), scan_game_libraries=False)

            with self.assertRaises(ConfigError):
                isolator.set_log_file(str(Path(tmpdir).parent / "escape.log"))


class ConfigHttpTests(unittest.TestCase):
    def _request_json(self, server, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            body = None
            headers = {}
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data
        finally:
            conn.close()

    def test_config_endpoints_read_defaults_and_write_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = IsolatorBridge(config_path=str(Path(tmpdir) / "config.json"))
            server = create_server(("127.0.0.1", 0), create_handler(bridge))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, defaults = self._request_json(server, "GET", "/api/config/defaults")
                self.assertEqual(200, status)
                self.assertIn("maintenance_jail_batch_size", defaults["defaults"])

                status, result = self._request_json(
                    server,
                    "PUT",
                    "/api/config",
                    {"games": ["cs2"], "enable_background_jailing": True},
                )
                self.assertEqual(200, status)
                self.assertEqual(["cs2.exe"], result["config"]["games"])
                self.assertFalse(result["restart_required"])

                status, current = self._request_json(server, "GET", "/api/config")
                self.assertEqual(200, status)
                self.assertTrue(current["config"]["enable_background_jailing"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_put_config_returns_400_for_invalid_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = IsolatorBridge(config_path=str(Path(tmpdir) / "config.json"))
            server = create_server(("127.0.0.1", 0), create_handler(bridge))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, result = self._request_json(
                    server,
                    "PUT",
                    "/api/config",
                    {"poll_interval_active_ms": 10},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(400, status)
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_config", result["error"])
        self.assertEqual("poll_interval_active_ms", result["errors"][0]["field"])

    def test_options_allows_put_for_config_editor(self):
        bridge = IsolatorBridge(config_path="__missing_config__.json")
        server = create_server(("127.0.0.1", 0), create_handler(bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            conn.request("OPTIONS", "/api/config", headers={"Origin": "http://localhost:5173"})
            response = conn.getresponse()
            response.read()
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(204, response.status)
        self.assertIn("PUT", response.getheader("Access-Control-Allow-Methods"))


if __name__ == "__main__":
    unittest.main()

import threading
import unittest
from pathlib import Path

from isolator.ifeo_power import IfeoPowerMixin
from isolator.winapi import HIGH_PERFORMANCE_GUID, ULTIMATE_PERFORMANCE_GUID, make_guid

BALANCED_GUID = (0x381B4222, 0xF694, 0x41F0, (0x96, 0x85, 0xFF, 0x5B, 0xB2, 0x60, 0xDF, 0x2E))
CUSTOM_GUID = (0xAAAAAAAA, 0xBBBB, 0xCCCC, (1, 2, 3, 4, 5, 6, 7, 8))


class DummyPower(IfeoPowerMixin):
    def __init__(self):
        self.ultimate_guid = make_guid(ULTIMATE_PERFORMANCE_GUID)
        self.high_performance_guid = make_guid(HIGH_PERFORMANCE_GUID)
        self.original_guid = make_guid(BALANCED_GUID)
        self.custom_guid = make_guid(CUSTOM_GUID)
        self._original_power_scheme = self.original_guid
        self._state_lock = threading.Lock()
        self._power_plan_active = False
        self._power_scheme_in_use = None
        self._disable_power_scheme_switch = False
        self._persistent_recovery_incomplete = False
        self.registered = [self.ultimate_guid]
        self.active_scheme = self.original_guid
        self.messages = []
        self.writes = []
        self.cleared = False
        self.set_calls = []

    def _log(self, message):
        self.messages.append(message)

    def _log_once(self, key, message):
        self.messages.append(message)

    def _write_power_recovery_state(self, **kwargs):
        self.writes.append(kwargs)
        return True

    def _clear_power_recovery_state(self):
        self.cleared = True

    def _enumerate_power_scheme_guids(self):
        return list(self.registered)

    def _set_power_scheme(self, guid):
        self.set_calls.append(guid)
        return True

    def _get_active_power_scheme(self):
        return self.active_scheme


class PowerSchemeCorrectnessTests(unittest.TestCase):
    def test_preferred_power_switch_requires_active_scheme_to_match_target(self):
        power = DummyPower()
        power.active_scheme = power.original_guid

        self.assertFalse(power._set_preferred_power_scheme())

        self.assertFalse(power._power_plan_active)
        self.assertIsNone(power._power_scheme_in_use)
        self.assertTrue(any(write.get("switched") is False for write in power.writes))
        self.assertIn("verify", " ".join(power.messages).lower())

    def test_unverified_success_is_not_overwritten_by_later_failed_candidate(self):
        power = DummyPower()
        power.registered = [power.ultimate_guid, power.high_performance_guid]
        power.active_scheme = power.original_guid

        def set_power(guid):
            power.set_calls.append(guid)
            return guid is power.ultimate_guid

        power._set_power_scheme = set_power

        self.assertFalse(power._set_preferred_power_scheme())

        self.assertTrue(power._power_scheme_set_unverified)
        self.assertEqual("ultimate", power._power_scheme_unverified_in_use)
        self.assertEqual(
            {"original_scheme": power.original_guid, "switched": True, "scheme_in_use": "ultimate"},
            power.writes[-1],
        )

    def test_restore_skips_when_user_changed_power_scheme_manually(self):
        power = DummyPower()
        power._power_plan_active = True
        power._power_scheme_in_use = "ultimate"
        power.active_scheme = power.custom_guid

        power._restore_power_scheme()

        self.assertEqual([], power.set_calls)
        self.assertTrue(power.cleared)
        self.assertFalse(power._power_plan_active)
        self.assertIsNone(power._power_scheme_in_use)
        self.assertIn("external", " ".join(power.messages).lower())

    def test_power_scheme_round_trip_restores_original_when_target_still_active(self):
        power = DummyPower()
        power.active_scheme = power.ultimate_guid

        self.assertTrue(power._set_preferred_power_scheme())
        self.assertTrue(power._power_plan_active)
        self.assertEqual("ultimate", power._power_scheme_in_use)

        power._restore_power_scheme()

        self.assertIs(power.set_calls[-1], power.original_guid)
        self.assertTrue(power.cleared)
        self.assertFalse(power._power_plan_active)

    def test_game_exit_restores_unverified_power_switch(self):
        source = (Path(__file__).resolve().parents[1] / "isolator" / "runtime.py").read_text(encoding="utf-8")

        self.assertIn('self._power_plan_active or getattr(self, "_power_scheme_set_unverified", False)', source)


if __name__ == "__main__":
    unittest.main()

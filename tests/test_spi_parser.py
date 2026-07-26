import ctypes
import unittest
from ctypes import wintypes
from unittest import mock

from isolator.app import EsportsIsolatorPro
from isolator.winapi import (
    STATUS_INFO_LENGTH_MISMATCH,
    SYSTEM_PROCESS_INFORMATION,
)

_ENTRY_SIZE = ctypes.sizeof(SYSTEM_PROCESS_INFORMATION)


def _build_spi_payload(specs):
    """Serialize SYSTEM_PROCESS_INFORMATION entries the way the kernel lays them out.

    Each spec: {"pid": int, "create_time": int, "name": str | None} plus an
    optional "dangling_length" to model an entry whose ImageName.Length is
    non-zero but whose Buffer pointer is NULL.

    Returns (payload_bytes, keepalive). The caller MUST keep `keepalive`
    referenced until _get_processes has run: the payload embeds real pointers
    into those wchar buffers and ctypes.wstring_at dereferences them.
    """
    entries = []
    keepalive = []
    for index, spec in enumerate(specs):
        entry = SYSTEM_PROCESS_INFORMATION()
        entry.NextEntryOffset = 0 if index == len(specs) - 1 else _ENTRY_SIZE
        entry.UniqueProcessId = spec["pid"]
        entry.CreateTime = spec.get("create_time", 0)
        name = spec.get("name")
        if name is not None:
            name_buf = ctypes.create_unicode_buffer(name)
            keepalive.append(name_buf)
            entry.ImageName.Length = len(name) * 2
            entry.ImageName.MaximumLength = (len(name) + 1) * 2
            entry.ImageName.Buffer = ctypes.cast(name_buf, wintypes.LPWSTR)
        elif spec.get("dangling_length"):
            entry.ImageName.Length = int(spec["dangling_length"])
            entry.ImageName.Buffer = None
        entries.append(entry)
    payload = b"".join(bytes(entry) for entry in entries)
    return payload, keepalive


class SpiParserTests(unittest.TestCase):
    def _make_isolator(self):
        isolator = EsportsIsolatorPro(
            config_path="__no_local_config__.json",
            scan_game_libraries=False,
        )
        isolator.messages = []
        isolator._log = isolator.messages.append
        return isolator

    def test_parses_pids_names_and_create_times_from_chained_entries(self):
        isolator = self._make_isolator()
        payload, keepalive = _build_spi_payload([
            {"pid": 4242, "name": "CS2.exe", "create_time": 111111},
            {"pid": 4300, "name": "Steam.exe", "create_time": 222222},
        ])
        calls = []

        def query(info_class, buffer, buffer_size, _returned):
            calls.append((info_class, ctypes.sizeof(buffer)))
            ctypes.memmove(buffer, payload, len(payload))
            buffer_size.value = len(payload)
            return 0

        with mock.patch(
            "isolator.discovery.ntdll.NtQuerySystemInformation", side_effect=query
        ):
            processes = isolator._get_processes()

        # Names come back lowercased via _normalize_spi_name.
        self.assertEqual([(4242, "cs2.exe"), (4300, "steam.exe")], processes)
        self.assertEqual({4242: 111111, 4300: 222222}, isolator._process_create_times)
        self.assertEqual(1, len(calls))
        self.assertEqual(5, calls[0][0])  # SystemProcessInformation class
        del keepalive

    def test_info_length_mismatch_grows_buffer_and_retries(self):
        isolator = self._make_isolator()
        payload, keepalive = _build_spi_payload([
            {"pid": 4242, "name": "cs2.exe", "create_time": 111111},
        ])
        initial_size = ctypes.sizeof(isolator._spi_buffer)
        required = 3 * 1024 * 1024
        call_sizes = []

        def query(_info_class, buffer, buffer_size, _returned):
            call_sizes.append(ctypes.sizeof(buffer))
            if len(call_sizes) == 1:
                buffer_size.value = required
                return STATUS_INFO_LENGTH_MISMATCH
            self.assertGreaterEqual(ctypes.sizeof(buffer), required)
            ctypes.memmove(buffer, payload, len(payload))
            buffer_size.value = len(payload)
            return 0

        with mock.patch(
            "isolator.discovery.ntdll.NtQuerySystemInformation", side_effect=query
        ):
            processes = isolator._get_processes()

        self.assertEqual([(4242, "cs2.exe")], processes)
        self.assertEqual(2, len(call_sizes))
        self.assertEqual(initial_size, call_sizes[0])
        # Grow rule: max(required, current) + 1MB.
        self.assertEqual(required + 1024 * 1024, call_sizes[1])
        del keepalive

    def test_null_or_zero_length_image_names_yield_empty_names(self):
        isolator = self._make_isolator()
        payload, keepalive = _build_spi_payload([
            # System Idle style: pid 0, Length 0, NULL Buffer.
            {"pid": 0, "name": None, "create_time": 0},
            # Defensive case: non-zero Length but NULL Buffer pointer.
            {"pid": 4, "dangling_length": 12, "create_time": 333},
            {"pid": 777, "name": "game.exe", "create_time": 444},
        ])

        def query(_info_class, buffer, buffer_size, _returned):
            ctypes.memmove(buffer, payload, len(payload))
            buffer_size.value = len(payload)
            return 0

        with mock.patch(
            "isolator.discovery.ntdll.NtQuerySystemInformation", side_effect=query
        ):
            processes = isolator._get_processes()

        self.assertEqual([(0, ""), (4, ""), (777, "game.exe")], processes)
        # pid 0 is falsy so it must not be recorded in the create-time map.
        self.assertNotIn(0, isolator._process_create_times)
        self.assertEqual({4: 333, 777: 444}, isolator._process_create_times)
        del keepalive


if __name__ == "__main__":
    unittest.main()

"""Read-only MSI mode registry inspection for PCI devices."""

import os
import time

TARGET_DEVICE_CLASSES = {"Display", "SCSIAdapter", "Net", "HDC", "USB"}
PCI_ENUM_PATH = r"SYSTEM\CurrentControlSet\Enum\PCI"
MSI_PROPERTIES_SUBKEY = r"Device Parameters\Interrupt Management\MessageSignaledInterruptProperties"


def _clean_device_name(value):
    text = str(value or "").strip()
    if ";" in text:
        text = text.split(";")[-1].strip()
    return text


def _query_value(winreg, key, name, default=None):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_subkeys(winreg, key):
    index = 0
    while True:
        try:
            yield winreg.EnumKey(key, index)
        except OSError:
            break
        index += 1


def read_msi_devices():
    if os.name != "nt":
        return False, "windows_only", []
    try:
        import winreg
    except ImportError:
        return False, "winreg_unavailable", []

    devices = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PCI_ENUM_PATH) as root:
            for device_key_name in _enum_subkeys(winreg, root):
                try:
                    device_key = winreg.OpenKey(root, device_key_name)
                except OSError:
                    continue
                with device_key:
                    for instance_name in _enum_subkeys(winreg, device_key):
                        try:
                            instance_key = winreg.OpenKey(device_key, instance_name)
                        except OSError:
                            continue
                        with instance_key:
                            device_class = str(_query_value(winreg, instance_key, "Class", "") or "")
                            if device_class and device_class not in TARGET_DEVICE_CLASSES:
                                continue
                            name = (
                                _clean_device_name(_query_value(winreg, instance_key, "FriendlyName", ""))
                                or _clean_device_name(_query_value(winreg, instance_key, "DeviceDesc", ""))
                                or device_key_name
                            )
                            msi_enabled = None
                            message_limit = None
                            try:
                                with winreg.OpenKey(instance_key, MSI_PROPERTIES_SUBKEY) as msi_key:
                                    supported = _query_value(winreg, msi_key, "MSISupported", None)
                                    if supported is not None:
                                        parsed_supported = _safe_int(supported)
                                        if parsed_supported is not None:
                                            msi_enabled = bool(parsed_supported)
                                    limit = _query_value(winreg, msi_key, "MessageNumberLimit", None)
                                    if limit is not None:
                                        message_limit = _safe_int(limit)
                            except OSError:
                                pass
                            devices.append({
                                "instance_id": f"PCI\\{device_key_name}\\{instance_name}",
                                "name": name,
                                "device_class": device_class or "PCI device",
                                "msi_enabled": msi_enabled,
                                "message_limit": message_limit,
                            })
    except PermissionError:
        return False, "access_denied", []
    except OSError as exc:
        return False, type(exc).__name__, []

    devices.sort(key=lambda item: (item["device_class"], item["name"], item["instance_id"]))
    return True, None, devices


def build_msi_payload(status, devices=None, available=True, reason=None, cache_hit=False, generated_at=None, cache_ttl_s=300):
    status = dict(status or {})
    if status.get("game_mode"):
        return {
            "ok": True,
            "available": False,
            "reason": "paused_in_game_mode",
            "readonly": True,
            "restart_required": True,
            "summary": {"total": 0, "enabled": 0, "disabled": 0, "unknown": 0},
            "devices": [],
            "cache": {"hit": bool(cache_hit), "ttl_s": int(cache_ttl_s), "generated_at": generated_at},
        }

    normalized_devices = []
    for device in devices or []:
        msi_enabled = device.get("msi_enabled")
        if msi_enabled is not None:
            msi_enabled = bool(msi_enabled)
        normalized_devices.append({
            "instance_id": str(device.get("instance_id", "")),
            "name": str(device.get("name", "") or "PCI device"),
            "device_class": str(device.get("device_class", "") or "PCI device"),
            "msi_enabled": msi_enabled,
            "message_limit": device.get("message_limit"),
        })

    enabled = sum(1 for device in normalized_devices if device["msi_enabled"] is True)
    disabled = sum(1 for device in normalized_devices if device["msi_enabled"] is False)
    unknown = len(normalized_devices) - enabled - disabled
    return {
        "ok": True,
        "available": bool(available),
        "reason": reason,
        "readonly": True,
        "restart_required": True,
        "summary": {
            "total": len(normalized_devices),
            "enabled": enabled,
            "disabled": disabled,
            "unknown": unknown,
        },
        "devices": normalized_devices if available else [],
        "cache": {
            "hit": bool(cache_hit),
            "ttl_s": int(cache_ttl_s),
            "generated_at": generated_at if generated_at is not None else time.time(),
        },
    }

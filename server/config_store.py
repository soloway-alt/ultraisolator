"""Config file loading, validation, and atomic writes for the API server."""

import json
import math
import os
import tempfile
import threading

DEFAULT_CONFIG = {
    "games": [
        "cs2.exe", "valorant.exe", "arcraiders.exe", "pioneergame.exe", "arcraiders-win64-shipping.exe",
        "bf2042.exe", "rustclient.exe", "dota2.exe", "deadlock.exe", "project8.exe", "tslgame.exe",
    ],
    "auto_detect_steam_games": True,
    "auto_detect_epic_games": True,
    "steam_library_paths": [],
    "epic_library_paths": [],
    "protected_extra": [],
    "app_profiles": [],
    "housekeeping_cores": 1,
    "hot_thread_limit": 4,
    "thread_sample_window_ms": 250,
    "poll_interval_idle_ms": 1000,
    "poll_interval_active_ms": 2000,
    "enable_background_jailing": False,
    "maintenance_jail_batch_size": 4,
    "maintenance_jail_interval_ms": 30000,
    "maintenance_jail_batch_cooldown_ms": 5000,
    "disable_timer_resolution_tweak": False,
    "disable_game_priority_boost": False,
    "game_close_debounce_s": 3,
    "game_exit_restore_delay_s": 10,
    "gc_full_collect_interval_s": 1800,
    "maintenance_skip_after_quiet_cycles": 3,
    "log_file": "",
    "enable_hot_thread_tuning": False,
    "hot_thread_refresh_ms": 1000,
    "anti_cheat_mode": "aggressive",
    "event_backend": "poll",
    "allow_mmcss_injection": False,
    "disable_power_scheme_switch": False,
}


CONFIG_SCHEMA = {
    "games": {"type": "string_list", "restart_required": True},
    "auto_detect_steam_games": {"type": "bool", "restart_required": True},
    "auto_detect_epic_games": {"type": "bool", "restart_required": True},
    "steam_library_paths": {"type": "string_list", "restart_required": True},
    "epic_library_paths": {"type": "string_list", "restart_required": True},
    "protected_extra": {"type": "string_list", "restart_required": True},
    "app_profiles": {
        "type": "app_profiles",
        "priority_choices": ["idle", "below_normal", "normal", "above_normal", "high"],
        "restart_required": True,
    },
    "housekeeping_cores": {"type": "int", "min": 1, "max": 16, "restart_required": True},
    "hot_thread_limit": {"type": "int", "min": 1, "max": 64, "restart_required": True},
    "thread_sample_window_ms": {"type": "int", "min": 50, "max": 5000, "restart_required": True},
    "poll_interval_idle_ms": {"type": "int", "min": 50, "max": 60000, "restart_required": True},
    "poll_interval_active_ms": {"type": "int", "min": 50, "max": 30000, "restart_required": True},
    "enable_background_jailing": {"type": "bool", "restart_required": True},
    "maintenance_jail_batch_size": {"type": "int", "min": 1, "max": 64, "restart_required": True},
    "maintenance_jail_interval_ms": {"type": "int", "min": 5000, "max": 300000, "restart_required": True},
    "maintenance_jail_batch_cooldown_ms": {"type": "int", "min": 1000, "max": 60000, "restart_required": True},
    "disable_timer_resolution_tweak": {"type": "bool", "restart_required": True},
    "disable_game_priority_boost": {"type": "bool", "restart_required": True},
    "game_close_debounce_s": {"type": "int", "min": 0, "max": 60, "restart_required": True},
    "game_exit_restore_delay_s": {"type": "float", "min": 0, "max": 300, "restart_required": True},
    "gc_full_collect_interval_s": {"type": "float", "min": 60, "max": 86400, "restart_required": True},
    "maintenance_skip_after_quiet_cycles": {"type": "int", "min": 0, "max": 100, "restart_required": True},
    "log_file": {"type": "string", "restart_required": True},
    "enable_hot_thread_tuning": {"type": "bool", "restart_required": True},
    "hot_thread_refresh_ms": {"type": "int", "min": 250, "max": 60000, "restart_required": True},
    "anti_cheat_mode": {"type": "choice", "choices": ["aggressive", "conservative"], "restart_required": True},
    "event_backend": {"type": "choice", "choices": ["poll"], "restart_required": True},
    "allow_mmcss_injection": {"type": "bool", "restart_required": True},
    "disable_power_scheme_switch": {"type": "bool", "restart_required": True},
}


class ConfigError(ValueError):
    def __init__(self, errors):
        super().__init__("invalid config")
        self.errors = errors


def _copy_defaults():
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in DEFAULT_CONFIG.items()
    }


def _normalize_exe_name(value):
    text = os.path.basename(str(value)).strip().lower()
    text = text.rstrip(". \t")
    while text.endswith(".exe.exe"):
        text = text[:-4]
    if text and "." not in text:
        text += ".exe"
    return text


def _coerce_bool(field, value):
    if isinstance(value, bool):
        return value, None
    return None, f"{field} must be a boolean."


def _coerce_int(field, value, minimum, maximum):
    if isinstance(value, bool):
        return None, f"{field} must be an integer."
    if isinstance(value, float):
        return None, f"{field} must be an integer."
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None, f"{field} must be an integer."
    if coerced < minimum:
        return None, f"{field} must be >= {minimum}."
    if coerced > maximum:
        return None, f"{field} must be <= {maximum}."
    return coerced, None


def _coerce_float(field, value, minimum, maximum):
    if isinstance(value, bool):
        return None, f"{field} must be a number."
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None, f"{field} must be a number."
    if not math.isfinite(coerced):
        return None, f"{field} must be a finite number."
    if coerced < minimum:
        return None, f"{field} must be >= {minimum}."
    if coerced > maximum:
        return None, f"{field} must be <= {maximum}."
    return coerced, None


def _coerce_string_list(field, value):
    if not isinstance(value, list):
        return None, f"{field} must be a list of strings."
    result = []
    for item in value:
        if not isinstance(item, str):
            return None, f"{field} must be a list of strings."
        stripped = item.strip()
        if stripped:
            result.append(_normalize_exe_name(stripped) if field == "games" else stripped)
    return result, None


# FIX 8: path-validation helpers. log_file is opened for append by the
# privileged engine (arbitrary file write) and the library path lists drive
# privileged directory walks, so they are confined / sanitized here.

def _is_unc_path(text):
    # Reject UNC / SMB shares (\\server\share or //server/share).
    return text.startswith("\\\\") or text.startswith("//")


def _has_traversal(text):
    # Reject any ".." path component on either separator style.
    parts = text.replace("\\", "/").split("/")
    return any(part == ".." for part in parts)


def _is_absolute_path(text):
    # Platform-independent absolute check: POSIX root or Windows drive (C:\...).
    # The engine is privileged on Windows, so accept drive-letter paths even
    # when validation happens to run off-Windows.
    if os.path.isabs(text):
        return True
    return len(text) >= 3 and text[1] == ":" and text[2] in ("\\", "/") and text[0].isalpha()


def _validate_log_file(field, value, base_dir):
    # Empty string disables file logging — always allowed.
    if not value:
        return value, None
    if _is_unc_path(value):
        return None, f"{field} must not be a UNC/network path."
    if _has_traversal(value):
        return None, f"{field} must not contain '..' path segments."
    # Confine to base_dir: resolve the candidate against base_dir and require
    # the result to stay inside it. This rejects absolute paths that escape the
    # app working directory while still accepting plain relative file names.
    base_real = os.path.realpath(base_dir)
    candidate = value if _is_absolute_path(value) else os.path.join(base_real, value)
    candidate_real = os.path.realpath(candidate)
    if candidate_real != base_real and not candidate_real.startswith(base_real + os.sep):
        return None, f"{field} must stay within the application directory."
    return candidate_real, None


def _validate_library_paths(field, values):
    # values is the already-coerced list of non-empty strings.
    for entry in values:
        if _is_unc_path(entry):
            return None, f"{field} must not contain UNC/network paths."
        if _has_traversal(entry):
            return None, f"{field} must not contain '..' path segments."
        if not _is_absolute_path(entry):
            return None, f"{field} entries must be absolute local paths."
    return values, None


def _coerce_app_profiles(field, value, spec):
    if not isinstance(value, list):
        return None, f"{field} must be a list of profile objects."
    profiles = []
    errors = []
    seen = set()
    priority_choices = set(spec["priority_choices"])
    for index, item in enumerate(value):
        prefix = f"{field}[{index}]"
        if not isinstance(item, dict):
            errors.append({"field": prefix, "message": f"{prefix} must be an object."})
            continue
        exe = _normalize_exe_name(item.get("exe", ""))
        if not exe:
            errors.append({"field": f"{prefix}.exe", "message": "Profile executable is required."})
        elif exe in seen:
            errors.append({"field": f"{prefix}.exe", "message": f"Duplicate profile executable: {exe}."})
        seen.add(exe)

        profile = {
            "exe": exe,
            "enabled": item.get("enabled", True),
            "treat_as_game": item.get("treat_as_game", False),
            "never_jail": item.get("never_jail", False),
            "always_jail": item.get("always_jail", False),
            "priority_class": item.get("priority_class", ""),
        }
        for flag in ("enabled", "treat_as_game", "never_jail", "always_jail"):
            coerced, error = _coerce_bool(f"{prefix}.{flag}", profile[flag])
            if error:
                errors.append({"field": f"{prefix}.{flag}", "message": error})
            else:
                profile[flag] = coerced
        priority = str(profile["priority_class"] or "").strip().lower()
        if priority and priority not in priority_choices:
            errors.append({
                "field": f"{prefix}.priority_class",
                "message": f"{prefix}.priority_class must be one of: {', '.join(spec['priority_choices'])}.",
            })
        profile["priority_class"] = priority
        if profile["never_jail"] and profile["always_jail"]:
            errors.append({"field": prefix, "message": "Profile cannot enable both never_jail and always_jail."})
        if exe:
            profiles.append(profile)
    if errors:
        return None, errors
    return profiles, None


def _validate_field(field, value, spec):
    kind = spec["type"]
    if kind == "bool":
        return _coerce_bool(field, value)
    if kind == "int":
        return _coerce_int(field, value, spec["min"], spec["max"])
    if kind == "float":
        return _coerce_float(field, value, spec["min"], spec["max"])
    if kind == "string":
        if isinstance(value, str):
            return value, None
        return None, f"{field} must be a string."
    if kind == "string_list":
        return _coerce_string_list(field, value)
    if kind == "app_profiles":
        return _coerce_app_profiles(field, value, spec)
    if kind == "choice":
        if not isinstance(value, str):
            return None, f"{field} must be one of: {', '.join(spec['choices'])}."
        lowered = value.strip().lower()
        if lowered in spec["choices"]:
            return lowered, None
        return None, f"{field} must be one of: {', '.join(spec['choices'])}."
    return None, f"{field} has unsupported schema type."


class ConfigStore:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        # Serializes update()'s read-modify-write; the ThreadingHTTPServer
        # drives one store instance from concurrent request threads.
        self._write_lock = threading.Lock()

    def defaults_response(self):
        return {
            "defaults": _copy_defaults(),
            "schema": CONFIG_SCHEMA,
            "reload": {
                "hot_reloadable": [],
                "restart_required_when_running": True,
            },
        }

    def read_raw(self):
        if not os.path.exists(self.config_path):
            return {}, False
        with open(self.config_path, "r", encoding="utf-8") as handle:
            try:
                loaded = json.load(
                    handle,
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid numeric constant: {value}")),
                )
            except ValueError as exc:
                raise ConfigError([{"field": "$", "message": f"config file must be valid JSON: {exc}"}]) from exc
        if not isinstance(loaded, dict):
            raise ConfigError([{"field": "$", "message": "config file must contain a JSON object."}])
        return loaded, True

    def read(self):
        loaded, exists = self.read_raw()
        config = self.validate(loaded, partial=True)
        return {
            "config": config,
            "exists": exists,
            "path": self.config_path,
            "reload": {
                "hot_reloadable": [],
                "restart_required_when_running": True,
            },
        }

    def validate(self, candidate, partial=False):
        if not isinstance(candidate, dict):
            raise ConfigError([{"field": "$", "message": "config must be a JSON object."}])
        errors = []
        unknown = sorted(set(candidate) - set(CONFIG_SCHEMA))
        for field in unknown:
            errors.append({"field": field, "message": f"Unknown config field: {field}."})

        config = _copy_defaults()
        base_dir = os.path.dirname(os.path.abspath(self.config_path)) or os.getcwd()
        fields = candidate.keys() if partial else CONFIG_SCHEMA.keys()
        for field in fields:
            if field not in CONFIG_SCHEMA:
                continue
            value, error = _validate_field(field, candidate.get(field, DEFAULT_CONFIG[field]), CONFIG_SCHEMA[field])
            if error:
                if isinstance(error, list):
                    errors.extend(error)
                else:
                    errors.append({"field": field, "message": error})
                continue
            # FIX 8: confine privileged path inputs after base coercion.
            if field == "log_file":
                value, error = _validate_log_file(field, value, base_dir)
            elif field in ("steam_library_paths", "epic_library_paths"):
                value, error = _validate_library_paths(field, value)
            if error:
                errors.append({"field": field, "message": error})
            else:
                config[field] = value

        if errors:
            raise ConfigError(errors)
        return config

    def update(self, candidate, running=False):
        with self._write_lock:
            loaded, _exists = self.read_raw()
            merged = dict(loaded)
            merged.update(candidate)
            config = self.validate(merged, partial=True)
            directory = os.path.dirname(os.path.abspath(self.config_path))
            os.makedirs(directory, exist_ok=True)
            # A unique temp file per write so overlapping writers (other
            # ConfigStore instances on the same path) can never truncate or
            # publish each other's partial content.
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(config, handle, indent=2, allow_nan=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.config_path)
            except Exception:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        return {
            "ok": True,
            "config": config,
            "restart_required": bool(running),
            "reload": {
                "hot_reloadable": [],
                "restart_required_when_running": True,
            },
        }

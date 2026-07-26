"""Protected recovery-state file helpers."""

import base64
import csv
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import tempfile


PROTECTED_STATE_VERSION = 2
PROTECTED_STATE_APP_DIR = "EsportsIsolatorPRO"
PROTECTED_STATE_KEY_FILE = "recovery-state.hmac.key"
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
STANDARD_USER_SIDS = frozenset({
    "S-1-1-0",
    "S-1-5-11",
    "S-1-5-32-545",
})
WRITE_RIGHTS_MASK = (
    0x00000002  # WriteData / CreateFiles
    | 0x00000004  # AppendData / CreateDirectories
    | 0x00000010  # WriteExtendedAttributes
    | 0x00000040  # DeleteSubdirectoriesAndFiles
    | 0x00000100  # WriteAttributes
    | 0x00010000  # Delete
    | 0x00040000  # ChangePermissions
    | 0x00080000  # TakeOwnership
)


class ProtectedStateError(ValueError):
    """Raised when protected recovery state cannot be trusted."""


# Paths whose ACL was applied and verified this session. The ACL layer shells
# out to powershell/icacls/whoami, so re-verifying the same recovery directory
# and files on every operation would put multiple process spawns on hot paths
# (jail-state records are written from the monitor thread). Once the parent
# directory is locked to SYSTEM/Administrators with inheritance, files created
# inside it inherit that ACL, so a per-file verification only needs to happen
# once per session; changing the ACL afterwards would already require
# administrator rights.
_verified_protected_parents = set()
_verified_protected_files = set()


def reset_protected_state_cache_for_tests():
    _verified_protected_parents.clear()
    _verified_protected_files.clear()


def default_protected_state_dir():
    root = os.environ.get("ProgramData")
    if not root:
        root = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(root, PROTECTED_STATE_APP_DIR, "Recovery")


def canonical_json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def state_key_path(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)), PROTECTED_STATE_KEY_FILE)


def _run_icacls(args):
    try:
        return subprocess.run(
            ["icacls", *args],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["icacls", *args], 1, "", str(exc))


def _is_reparse_point(path):
    if not os.path.exists(path):
        return False
    if os.name != "nt":
        return os.path.islink(path)
    try:
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return True
    if attributes == 0xFFFFFFFF:
        return True
    return bool(attributes & 0x400)


def _current_user_sid():
    try:
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        rows = list(csv.reader(result.stdout.splitlines()))
    except csv.Error:
        return None
    if not rows or len(rows[0]) < 2:
        return None
    sid = rows[0][1].strip()
    return sid.upper() if sid.upper().startswith("S-") else None


def _acl_entries_for_path(path):
    script = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $args[0]
$acl.Access | ForEach-Object {
  $sid = try {
    $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
  } catch {
    $_.IdentityReference.Value
  }
  [pscustomobject]@{
    Sid = $sid
    Rights = [Int64]$_.FileSystemRights
    Type = $_.AccessControlType.ToString()
  }
} | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, path],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise ProtectedStateError("recovery state ACL could not be inspected") from exc
    if result.returncode != 0:
        raise ProtectedStateError("recovery state ACL could not be inspected")
    text = result.stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtectedStateError("recovery state ACL could not be inspected") from exc
    return parsed if isinstance(parsed, list) else [parsed]


def _acl_grants_untrusted_write(path):
    allowed_write_sids = {SYSTEM_SID, ADMINISTRATORS_SID}
    entries = _acl_entries_for_path(path)
    if not entries:
        return True
    for entry in entries:
        if not isinstance(entry, dict):
            return True
        if str(entry.get("Type", "")).lower() != "allow":
            continue
        sid = str(entry.get("Sid", "")).upper()
        try:
            rights = int(entry.get("Rights", 0))
        except (TypeError, ValueError):
            return True
        if rights & WRITE_RIGHTS_MASK and sid not in allowed_write_sids:
            return True
    return False


def apply_protected_state_acl(path):
    target = os.path.abspath(path)
    if os.name != "nt":
        try:
            os.chmod(target, 0o700 if os.path.isdir(target) else 0o600)
        except OSError:
            return False
        return True

    if _is_reparse_point(target):
        return False
    inherit = "(OI)(CI)" if os.path.isdir(target) else ""
    grants = [
        f"*S-1-5-18:{inherit}(F)",
        f"*S-1-5-32-544:{inherit}(F)",
    ]
    result = _run_icacls([target, "/inheritance:r", "/grant:r", *grants])
    if result.returncode != 0:
        return False
    remove_sids = [f"*{sid}" for sid in sorted(STANDARD_USER_SIDS)]
    current_sid = _current_user_sid()
    if current_sid and current_sid not in {SYSTEM_SID, ADMINISTRATORS_SID}:
        remove_sids.append(f"*{current_sid}")
    _run_icacls([target, "/remove:g", *remove_sids])
    return not _acl_grants_untrusted_write(target)


def ensure_protected_state_parent(path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory in _verified_protected_parents and os.path.isdir(directory):
        return directory
    os.makedirs(directory, exist_ok=True)
    if not apply_protected_state_acl(directory):
        raise ProtectedStateError("recovery state ACL could not be protected")
    _verified_protected_parents.add(directory)
    return directory


def is_protected_state_path_safe(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent in _verified_protected_parents and os.path.isdir(parent):
        targets = []
    else:
        targets = [parent]
    absolute = os.path.abspath(path)
    if os.path.exists(path) and absolute not in _verified_protected_files:
        targets.append(absolute)
    key_path = state_key_path(path)
    if os.path.exists(key_path) and key_path not in _verified_protected_files:
        targets.append(key_path)

    if os.name != "nt":
        for target in targets:
            try:
                if _is_reparse_point(target):
                    return False
                if os.stat(target).st_mode & 0o022:
                    return False
            except OSError:
                return False
        return True

    for target in targets:
        if _is_reparse_point(target):
            return False
        try:
            if _acl_grants_untrusted_write(target):
                return False
        except ProtectedStateError:
            return False
    return True


def _write_bytes_atomic(path, data):
    ensure_protected_state_parent(path)
    absolute = os.path.abspath(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=os.path.dirname(absolute))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        # First write per file per session: apply and verify the file ACL.
        # Later writes inherit the locked directory ACL through the mkstemp
        # temp file, so re-running the subprocess-backed verification would
        # only add process-spawn latency on the monitor thread.
        if absolute not in _verified_protected_files:
            if not apply_protected_state_acl(path) or not is_protected_state_path_safe(path):
                raise ProtectedStateError("recovery state ACL could not be protected")
            _verified_protected_files.add(absolute)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _load_or_create_key(path):
    key_path = state_key_path(path)
    if os.path.exists(key_path):
        try:
            with open(key_path, "rb") as handle:
                key = base64.b64decode(handle.read(), validate=True)
        except Exception as exc:
            raise ProtectedStateError("tampered recovery state key") from exc
        if len(key) != 32:
            raise ProtectedStateError("tampered recovery state key")
        return key

    key = secrets.token_bytes(32)
    _write_bytes_atomic(key_path, base64.b64encode(key))
    return key


def _load_existing_key(path):
    key_path = state_key_path(path)
    if not os.path.exists(key_path):
        raise ProtectedStateError("tampered recovery state: missing key")
    return _load_or_create_key(path)


def _signed_body(payload):
    return {"version": PROTECTED_STATE_VERSION, "payload": payload}


def _tag_for(key, body):
    return "sha256:" + hmac.new(key, canonical_json_bytes(body), hashlib.sha256).hexdigest()


def write_protected_state_file(path, payload):
    if not isinstance(payload, dict):
        raise ProtectedStateError("protected recovery state payload must be an object")
    key = _load_or_create_key(path)
    body = _signed_body(payload)
    envelope = {**body, "tag": _tag_for(key, body)}
    _write_bytes_atomic(path, canonical_json_bytes(envelope) + b"\n")
    return True


def read_protected_state_file(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            envelope = json.load(handle)
    except Exception as exc:
        raise ProtectedStateError("invalid protected recovery state") from exc
    if not isinstance(envelope, dict) or envelope.get("version") != PROTECTED_STATE_VERSION:
        raise ProtectedStateError("tampered or downgraded recovery state")
    payload = envelope.get("payload")
    tag = envelope.get("tag")
    if not isinstance(payload, dict) or not isinstance(tag, str):
        raise ProtectedStateError("invalid protected recovery state envelope")
    key = _load_existing_key(path)
    expected = _tag_for(key, _signed_body(payload))
    if not hmac.compare_digest(tag, expected):
        raise ProtectedStateError("tampered recovery state")
    return payload


def remove_protected_state_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

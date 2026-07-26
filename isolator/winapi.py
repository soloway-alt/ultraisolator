import ctypes
import os
import re
from ctypes import wintypes

from .protected_state import default_protected_state_dir

# WHY: The curated Win32/domain surface of this module. Engine modules import
# these names explicitly, and best_isolator.py star-imports exactly this list
# as its backward-compat re-export surface. Keep it in sync with the module
# body; ruff flags entries that do not exist (F822).
__all__ = [
    # Status / error codes
    "NTSTATUS",
    "STATUS_INFO_LENGTH_MISMATCH",
    "ERROR_ALREADY_EXISTS",
    "ERROR_INSUFFICIENT_BUFFER",
    "INVALID_HANDLE_VALUE",
    # Process/thread access rights and information classes
    "PROCESS_SET_INFORMATION",
    "PROCESS_QUERY_INFORMATION",
    "PROCESS_QUERY_LIMITED_INFORMATION",
    "PROCESS_SET_LIMITED_INFORMATION",
    "PROCESS_POWER_THROTTLING_CURRENT_VERSION",
    "PROCESS_POWER_THROTTLING_EXECUTION_SPEED",
    "PROCESS_INFORMATION_CLASS_POWER_THROTTLING",
    "PROCESS_INFORMATION_CLASS_IO_PRIORITY",
    "PROCESS_INFORMATION_CLASS_PAGE_PRIORITY",
    "THREAD_QUERY_INFORMATION",
    "THREAD_SET_INFORMATION",
    "THREAD_QUERY_LIMITED_INFORMATION",
    "THREAD_SET_LIMITED_INFORMATION",
    "THREAD_PRIORITY_HIGHEST",
    "THREAD_PRIORITY_ERROR_RETURN",
    "TH32CS_SNAPTHREAD",
    # Topology / CPU-set enumeration
    "RelationCache",
    "RelationAll",
    "CpuSetInformation",
    # Priority classes and page/IO priorities
    "IDLE_PRIORITY_CLASS",
    "BELOW_NORMAL_PRIORITY_CLASS",
    "NORMAL_PRIORITY_CLASS",
    "ABOVE_NORMAL_PRIORITY_CLASS",
    "HIGH_PRIORITY_CLASS",
    "PAGE_PRIORITY_MINIMUM",
    "PAGE_PRIORITY_NORMAL",
    "IO_PRIORITY_VERY_LOW",
    "IO_PRIORITY_NORMAL",
    # Singleton / recovery-state paths and policy
    "MUTEX_NAME",
    "RECOVERY_STATE_DIR",
    "IFEO_BACKUP_PATH",
    "RECOVERY_STATE_PATH",
    "RECOVERY_STATE_VERSION",
    "JAIL_STATE_PATH",
    "JAIL_STATE_VERSION",
    "JAIL_STATE_ENTRY_TTL_SECONDS",
    # Console control events
    "CTRL_C_EVENT",
    "CTRL_BREAK_EVENT",
    "CTRL_CLOSE_EVENT",
    "CTRL_LOGOFF_EVENT",
    "CTRL_SHUTDOWN_EVENT",
    "CONSOLE_CTRL_HANDLER",
    # IFEO policy
    "IFEO_VALUES",
    "IFEO_DENIED_EXES",
    # Non-game exe/path filtering
    "NON_GAME_EXE_NAME_PATTERN",
    "NON_GAME_PATH_TOKENS",
    "NON_GAME_DIR_PRUNE_TOKENS",
    # Power schemes
    "ULTIMATE_PERFORMANCE_GUID",
    "HIGH_PERFORMANCE_GUID",
    "POWER_ACCESS_SCHEME",
    # DLL handles (carry the ctypes prototypes declared below)
    "kernel32",
    "ntdll",
    "user32",
    "powrprof",
    "advapi32",
    # Token elevation
    "TOKEN_QUERY",
    "TokenElevation",
    # Structures
    "TOKEN_ELEVATION",
    "UNICODE_STRING",
    "SYSTEM_PROCESS_INFORMATION",
    "PROCESS_POWER_THROTTLING_STATE",
    "GUID",
    "PAGE_PRIORITY_INFORMATION",
    "GROUP_AFFINITY",
    "PROCESSOR_NUMBER",
    "THREADENTRY32",
    "CPU_SET_DATA",
    "SYSTEM_CPU_SET_INFORMATION",
    "CACHE_RELATIONSHIP",
    "SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX",
    "SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_CACHE",
    # Helpers
    "nt_success",
    "is_process_elevated",
    "make_guid",
]

NTSTATUS = wintypes.LONG
STATUS_INFO_LENGTH_MISMATCH = ctypes.c_long(0xC0000004).value
ERROR_ALREADY_EXISTS = 183

PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_LIMITED_INFORMATION = 0x2000

PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_INFORMATION_CLASS_POWER_THROTTLING = 4
PROCESS_INFORMATION_CLASS_IO_PRIORITY = 33
PROCESS_INFORMATION_CLASS_PAGE_PRIORITY = 39

THREAD_QUERY_INFORMATION = 0x0040
THREAD_SET_INFORMATION = 0x0020
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
THREAD_SET_LIMITED_INFORMATION = 0x0400

THREAD_PRIORITY_HIGHEST = 2
THREAD_PRIORITY_ERROR_RETURN = 0x7FFFFFFF

TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_INSUFFICIENT_BUFFER = 122

RelationCache = 2
RelationAll = 0xFFFF
CpuSetInformation = 0

IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS = 0x00000080

PAGE_PRIORITY_MINIMUM = 1
PAGE_PRIORITY_NORMAL = 5
IO_PRIORITY_VERY_LOW = 0
IO_PRIORITY_NORMAL = 2

MUTEX_NAME = r"Local\EsportsIsolatorProSingleton"
RECOVERY_STATE_DIR = default_protected_state_dir()
IFEO_BACKUP_PATH = os.path.join(RECOVERY_STATE_DIR, "ifeo_backup.json")
RECOVERY_STATE_PATH = os.path.join(RECOVERY_STATE_DIR, "recovery_state.json")
RECOVERY_STATE_VERSION = 2
# WHY: The jail crash-recovery record is consumed by an elevated process and
# feeds priority/affinity/EcoQoS values into _restore_process, so it must get
# the same protection as the IFEO and power recovery artifacts: the ACL-locked
# ProgramData recovery directory plus the HMAC envelope (see recovery.py). It
# previously lived unauthenticated in the writable install/repo root.
JAIL_STATE_PATH = os.path.join(RECOVERY_STATE_DIR, "jail_state.json")
JAIL_STATE_VERSION = 1
# WHY (item 10): This TTL is a CRASH-RECOVERY BACKSTOP only — it bounds how
# long a stale on-disk jail record (left by a hard crash) is trusted before we
# stop trying to "restore" a PID that has almost certainly been recycled. It
# was 6h, which wrongly dropped recovery records for genuinely long-lived
# jailed processes during long gaming/idle sessions. Raised to 24h so a normal
# multi-hour session never loses its ability to un-jail a still-running
# process on the next launch, while still discarding truly ancient records
# whose PID has near-certainly been reused.
JAIL_STATE_ENTRY_TTL_SECONDS = 24 * 60 * 60

# WHY: Windows Console Control Handler event codes. These are the signals
# delivered by the kernel when the user clicks the console window's "X" button
# (CTRL_CLOSE_EVENT), presses Ctrl+C (CTRL_C_EVENT), or the system shuts down.
# Standard Python atexit handlers and try/finally blocks do NOT fire for
# CTRL_CLOSE_EVENT on Windows — the process is forcefully terminated after the
# handler returns. We must use SetConsoleCtrlHandler to intercept these events.
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

IFEO_VALUES = {
    "CpuPriorityClass": 3,
    "IoPriority": IO_PRIORITY_NORMAL,
    "PagePriority": PAGE_PRIORITY_NORMAL,
}
# WHY (item 4): Writing IFEO CpuPriorityClass/PagePriority/IoPriority for
# core Windows system or critical exes can destabilize the session (jailing
# the shell, console host, font/audio drivers, input/session services). The
# previous list missed several commonly-running system binaries
# (conhost.exe, explorer.exe, RuntimeBroker.exe, ctfmon.exe, etc.). All names
# are stored canonicalized (basename, lower-case, single trailing .exe) and
# the denylist check canonicalizes its input the same way so bypass forms
# like "lsass.exe." or "..\\..\\lsass.exe" or "DWM.EXE " are still caught.
IFEO_DENIED_EXES = frozenset({
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "winlogon.exe",
    "svchost.exe", "spoolsv.exe", "dwm.exe", "audiodg.exe",
    "fontdrvhost.exe", "smartscreen.exe", "taskhostw.exe",
    "securityhealthservice.exe", "msmpeng.exe",
    # Shell / session / input / brokering exes that should never be jailed.
    "explorer.exe", "conhost.exe", "runtimebroker.exe", "ctfmon.exe",
    "sihost.exe", "taskhostex.exe", "dllhost.exe", "wmiprvse.exe",
    "searchindexer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "logonui.exe", "userinit.exe",
    "wudfhost.exe", "memcompression", "secure system",
    "registry.exe", "ntoskrnl.exe", "msdtc.exe", "trustedinstaller.exe",
    "wlms.exe",
})

# WHY: Steam and Epic library directories contain plenty of .exe files that
# are NOT games — Visual C++ / DirectX redistributables, anti-cheat installers,
# crash handlers, updaters, etc. Without filtering, those would be treated as
# games (boosted to HIGH priority, exempt from background jailing) which steals
# CPU from the actual game and produces misleading log lines. We exclude exes
# that match these patterns by name OR live under a path component named
# *redist* / *commonredist* / *_CommonRedist*.
# WHY: Patterns are anchored at the start of the filename. \b is used on
# generic terms (installer, update) so that filenames like "installerart.exe"
# (hypothetical game) are NOT excluded — only the explicit "installer.exe",
# "installer_x86.exe", "update.exe", etc. Note: "launcher" was removed
# because legitimate entry-point exes for some MMORPGs / PS Now use the
# literal name "Launcher.exe"; we filter those at the path-token level
# (e.g. \redist\) instead, which is safer than a name-only blacklist.
NON_GAME_EXE_NAME_PATTERN = re.compile(
    r"^(?:"
    r"vcredist|vc_redist|dxsetup|directx|dotnetfx|dotnet|ndp\d+|aspnet|"
    r"oalinst|xnafx|physx|nvngx|amd_|intel_|setup\b|installer\b|uninstall|"
    r"unins\d*|update\b|updater|patcher|crashhandler|crashreport|"
    r"crashpad_handler|errorreport|easyanticheat|battleye|beservice|vgc"
    r")",
    re.IGNORECASE,
)
NON_GAME_PATH_TOKENS = (
    "\\_commonredist\\",
    "\\commonredist\\",
    "\\redist\\",
    "\\redistributable\\",
    "\\redistributables\\",
    "\\directx\\",
    "\\vcredist\\",
    "\\dotnetfx\\",
    "\\easyanticheat\\",
    "\\battleye\\",
    "\\_installer\\",
    "\\installers\\",
)
# WHY: Pre-stripped, lower-cased prune tokens for substring matching in
# directory names during os.walk. Substring (not exact) match catches names
# like "Game Installers" or "_CommonRedist_x86" that the previous exact-
# match check missed — saving the recursive walk into known non-game subtrees.
NON_GAME_DIR_PRUNE_TOKENS = tuple(t.strip("\\").lower() for t in NON_GAME_PATH_TOKENS)

ULTIMATE_PERFORMANCE_GUID = (0xE9A42B02, 0xD5DF, 0x448D, (0xAA, 0x00, 0x03, 0xF1, 0x47, 0x49, 0xEB, 0x61))
HIGH_PERFORMANCE_GUID = (0x8C5E7FDA, 0xE8BF, 0x4A96, (0x9A, 0x85, 0xA6, 0xE2, 0x3A, 0x8C, 0x63, 0x5C))

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# WHY: Token-based elevation check (TokenElevation == 20) is the modern
# replacement for the deprecated IsUserAnAdmin. It correctly handles split
# tokens (UAC) where the admin SID is present but the token is filtered.
TOKEN_QUERY = 0x0008
TokenElevation = 20


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", wintypes.LPWSTR)]


class SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", wintypes.LARGE_INTEGER),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", wintypes.ULARGE_INTEGER),
        ("CreateTime", wintypes.LARGE_INTEGER),
        ("UserTime", wintypes.LARGE_INTEGER),
        ("KernelTime", wintypes.LARGE_INTEGER),
        ("ImageName", UNICODE_STRING),
        ("BasePriority", wintypes.LONG),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_void_p),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
    ]


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("ControlMask", wintypes.DWORD), ("StateMask", wintypes.DWORD)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PAGE_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("PagePriority", wintypes.ULONG)]


class GROUP_AFFINITY(ctypes.Structure):
    _fields_ = [("Mask", ctypes.c_size_t), ("Group", wintypes.WORD), ("Reserved", wintypes.WORD * 3)]


class PROCESSOR_NUMBER(ctypes.Structure):
    _fields_ = [("Group", wintypes.WORD), ("Number", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _CPU_SET_SCHEDULING_UNION(ctypes.Union):
    _fields_ = [
        ("Reserved", wintypes.DWORD),
        ("SchedulingClass", ctypes.c_ubyte),
    ]


class CPU_SET_DATA(ctypes.Structure):
    _anonymous_ = ("Scheduling",)
    _fields_ = [
        ("Id", wintypes.DWORD),
        ("Group", wintypes.WORD),
        ("LogicalProcessorIndex", ctypes.c_ubyte),
        ("CoreIndex", ctypes.c_ubyte),
        ("LastLevelCacheIndex", ctypes.c_ubyte),
        ("NumaNodeIndex", ctypes.c_ubyte),
        ("EfficiencyClass", ctypes.c_ubyte),
        ("AllFlags", ctypes.c_ubyte),
        ("Scheduling", _CPU_SET_SCHEDULING_UNION),
        ("AllocationTag", ctypes.c_ulonglong),
    ]


class SYSTEM_CPU_SET_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("CpuSet", CPU_SET_DATA),
    ]


class CACHE_RELATIONSHIP(ctypes.Structure):
    _fields_ = [
        ("Level", ctypes.c_ubyte),
        ("Associativity", ctypes.c_ubyte),
        ("LineSize", wintypes.WORD),
        ("CacheSize", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("Reserved", ctypes.c_ubyte * 18),
        ("GroupCount", wintypes.WORD),
        ("GroupMasks", GROUP_AFFINITY * 1),
    ]


class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(ctypes.Structure):
    _fields_ = [("Relationship", wintypes.DWORD), ("Size", wintypes.DWORD)]


class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX_CACHE(ctypes.Structure):
    _fields_ = [
        ("Relationship", wintypes.DWORD),
        ("Size", wintypes.DWORD),
        ("Cache", CACHE_RELATIONSHIP),
    ]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
kernel32.GetPriorityClass.restype = wintypes.DWORD
kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.SetPriorityClass.restype = wintypes.BOOL
kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
kernel32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
kernel32.SetProcessPriorityBoost.argtypes = [wintypes.HANDLE, wintypes.BOOL]
kernel32.SetProcessPriorityBoost.restype = wintypes.BOOL
kernel32.GetProcessPriorityBoost.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.GetProcessPriorityBoost.restype = wintypes.BOOL
kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
kernel32.SetProcessInformation.restype = wintypes.BOOL
kernel32.GetProcessInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
kernel32.GetProcessInformation.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p
kernel32.GetLogicalProcessorInformationEx.argtypes = [wintypes.DWORD, wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetLogicalProcessorInformationEx.restype = wintypes.BOOL
kernel32.GetSystemCpuSetInformation.argtypes = [wintypes.LPVOID, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.HANDLE, wintypes.ULONG]
kernel32.GetSystemCpuSetInformation.restype = wintypes.BOOL
kernel32.SetProcessDefaultCpuSets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
kernel32.SetProcessDefaultCpuSets.restype = wintypes.BOOL
kernel32.GetProcessDefaultCpuSets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
kernel32.GetProcessDefaultCpuSets.restype = wintypes.BOOL
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenThread.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32First.restype = wintypes.BOOL
kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32Next.restype = wintypes.BOOL
kernel32.GetThreadTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
kernel32.GetThreadTimes.restype = wintypes.BOOL
kernel32.QueryThreadCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
kernel32.QueryThreadCycleTime.restype = wintypes.BOOL
kernel32.GetThreadPriority.argtypes = [wintypes.HANDLE]
kernel32.GetThreadPriority.restype = wintypes.INT
kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, wintypes.INT]
kernel32.SetThreadPriority.restype = wintypes.BOOL
kernel32.GetThreadIdealProcessorEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSOR_NUMBER)]
kernel32.GetThreadIdealProcessorEx.restype = wintypes.BOOL
kernel32.SetThreadIdealProcessorEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSOR_NUMBER), ctypes.POINTER(PROCESSOR_NUMBER)]
kernel32.SetThreadIdealProcessorEx.restype = wintypes.BOOL
kernel32.SetThreadGroupAffinity.argtypes = [wintypes.HANDLE, ctypes.POINTER(GROUP_AFFINITY), ctypes.POINTER(GROUP_AFFINITY)]
kernel32.SetThreadGroupAffinity.restype = wintypes.BOOL
kernel32.SetThreadSelectedCpuSets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
kernel32.SetThreadSelectedCpuSets.restype = wintypes.BOOL
kernel32.GetThreadSelectedCpuSets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
kernel32.GetThreadSelectedCpuSets.restype = wintypes.BOOL
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsWow64Process.restype = wintypes.BOOL

ntdll.NtQuerySystemInformation.argtypes = [wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
ntdll.NtQuerySystemInformation.restype = NTSTATUS
ntdll.NtSetInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG]
ntdll.NtSetInformationProcess.restype = NTSTATUS
ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
ntdll.NtQueryInformationProcess.restype = NTSTATUS
ntdll.NtQueryTimerResolution.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG)]
ntdll.NtQueryTimerResolution.restype = NTSTATUS
ntdll.NtSetTimerResolution.argtypes = [wintypes.ULONG, wintypes.BOOLEAN, ctypes.POINTER(wintypes.ULONG)]
ntdll.NtSetTimerResolution.restype = NTSTATUS

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

powrprof.PowerGetActiveScheme.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.POINTER(GUID))]
powrprof.PowerGetActiveScheme.restype = wintypes.DWORD
powrprof.PowerSetActiveScheme.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID)]
powrprof.PowerSetActiveScheme.restype = wintypes.DWORD
# WHY: PowerEnumerate lets us list the power schemes that ARE registered on
# this machine. We use it to verify a target GUID exists before calling
# PowerSetActiveScheme — some Windows editions / OEM driver stacks have been
# reported to leave "Ultimate Performance" duplicate plans behind when the
# well-known template GUID is activated on a system where it was not
# pre-registered. Checking existence first avoids any such side-effects.
powrprof.PowerEnumerate.argtypes = [
    wintypes.HANDLE,                          # RootPowerKey (NULL)
    ctypes.POINTER(GUID),                     # SchemeGuid (NULL for scheme enum)
    ctypes.POINTER(GUID),                     # SubGroupOfPowerSettingsGuid (NULL)
    wintypes.ULONG,                           # AccessFlags
    wintypes.ULONG,                           # Index
    ctypes.POINTER(ctypes.c_ubyte),           # Buffer (out: GUID for SCHEME)
    ctypes.POINTER(wintypes.DWORD),           # BufferSize
]
powrprof.PowerEnumerate.restype = wintypes.DWORD
POWER_ACCESS_SCHEME = 16  # ACCESS_SCHEME constant from PowrProf.h

advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
advapi32.GetTokenInformation.restype = wintypes.BOOL

# WHY: SetConsoleCtrlHandler requires a PHANDLER_ROUTINE callback with signature
# BOOL WINAPI HandlerRoutine(DWORD dwCtrlType). We define the WINFUNCTYPE here
# so the callback pointer persists for the lifetime of the process — if it were
# a local variable, Python's GC could collect it and the kernel would call into
# freed memory on the next console event.
CONSOLE_CTRL_HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
kernel32.SetConsoleCtrlHandler.argtypes = [CONSOLE_CTRL_HANDLER, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL


def nt_success(status):
    return int(status) >= 0


def is_process_elevated():
    """Return True only when the current Windows token is elevated."""
    if os.name != "nt":
        return False
    token_handle = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(
                kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token_handle)):
            return False
        elevation = TOKEN_ELEVATION()
        returned = wintypes.DWORD()
        if not advapi32.GetTokenInformation(
                token_handle, TokenElevation,
                ctypes.byref(elevation), ctypes.sizeof(elevation),
                ctypes.byref(returned)):
            return False
        return bool(elevation.TokenIsElevated)
    except Exception:
        return False
    finally:
        if token_handle:
            kernel32.CloseHandle(token_handle)


def make_guid(guid_tuple):
    data1, data2, data3, data4 = guid_tuple
    return GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*data4))

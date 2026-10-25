"""Small Windows integration layer for the desktop companion (stdlib ctypes only).

- SingleInstance: a named mutex so a second launch only focuses the existing companion.
- HotkeyListener: RegisterHotKey (default Ctrl+Alt+T, configurable) on a message-loop thread.
- find_window / focus_window: bring the existing companion window to the front.
- open_app_window: Edge in --app mode with a dedicated profile (compact window, no tabs).
- show_toast: a Windows toast via Windows PowerShell's WinRT bridge. Text is passed through an
  environment variable, never interpolated into the script, so it cannot inject commands.

Every function degrades gracefully on non-Windows systems (returns False / raises clearly).
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
from xml.sax.saxutils import escape, quoteattr

IS_WINDOWS = sys.platform == "win32"

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_SPACE = 0x20
WM_HOTKEY, WM_QUIT, WM_CLOSE = 0x0312, 0x0012, 0x0010
ERROR_ALREADY_EXISTS = 183
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
SW_RESTORE, SW_SHOW = 9, 5
CREATE_NO_WINDOW = 0x08000000
COMPANION_TITLE = "TaskMaster Companion"
# Windows PowerShell's registered AppUserModelID: lets an unpackaged app show toasts with no installer.
POWERSHELL_AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

if IS_WINDOWS:
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": 0x0004, "win": 0x0008}
NAMED_KEYS = {"space": VK_SPACE, "enter": 0x0D, "tab": 0x09, "home": 0x24, "end": 0x23, "insert": 0x2D,
              "pause": 0x13, "scrolllock": 0x91, **{f"f{i}": 0x6F + i for i in range(1, 13)}}


def parse_hotkey(text):
    """'ctrl+alt+space' -> (modifiers, virtual key). Requires ctrl, alt or win so a bare key can
    never be captured system-wide."""
    parts = [p.strip().lower() for p in str(text or "").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("use a modifier plus a key, e.g. ctrl+alt+space")
    mods = 0
    for p in parts[:-1]:
        if p not in MODIFIERS:
            raise ValueError(f"unknown modifier {p!r} (use ctrl, alt, shift, win)")
        mods |= MODIFIERS[p]
    if not mods & (MOD_CONTROL | MOD_ALT | MODIFIERS["win"]):
        raise ValueError("include ctrl, alt or win")
    k = parts[-1]
    if k in NAMED_KEYS:
        vk = NAMED_KEYS[k]
    elif len(k) == 1 and k.isascii() and k.isalnum():
        vk = ord(k.upper())
    else:
        raise ValueError(f"unsupported key {k!r} (use a letter, digit, space or f1-f12)")
    return mods, vk


def format_hotkey(text):
    return "+".join(p.strip().capitalize() for p in str(text).split("+"))


class SingleInstance:
    """Named mutex. `already_running` is True when another companion holds it."""

    def __init__(self, name="Local\\TaskMasterCompanion"):
        self.handle = None
        self.already_running = False
        if not IS_WINDOWS:
            return
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


class HotkeyListener(threading.Thread):
    """Registers the hotkey (default Ctrl+Alt+T) and calls `callback` on each press. If registration fails
    (e.g. another program owns the shortcut) it records why and does nothing else."""

    def __init__(self, callback, hotkey="ctrl+alt+t"):
        super().__init__(name="taskmaster-hotkey", daemon=True)
        self.callback = callback
        self.label = format_hotkey(hotkey)
        self.modifiers, self.vk = parse_hotkey(hotkey)
        self.registered = False
        self.error = None
        self.presses = 0
        self.ready = threading.Event()
        self._tid = None

    def run(self):
        if not IS_WINDOWS:
            self.error = "global hotkeys need Windows"
            self.ready.set()
            return
        self._tid = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.modifiers | MOD_NOREPEAT, self.vk):
            code = ctypes.get_last_error()
            self.error = (f"{self.label} is already used by another program" if code == ERROR_HOTKEY_ALREADY_REGISTERED
                          else f"RegisterHotKey failed for {self.label} (Windows error {code})")
            self.ready.set()
            return
        self.registered = True
        self.ready.set()
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.presses += 1
                    try:
                        self.callback()
                    except Exception as e:  # keep the hotkey alive; report the failure
                        print(f"[companion] hotkey action failed: {e!r}", flush=True)
        finally:
            user32.UnregisterHotKey(None, 1)
            self.registered = False

    def stop(self):
        if IS_WINDOWS and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


def find_windows(title_part=COMPANION_TITLE):
    if not IS_WINDOWS:
        return []
    found = []

    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def focus_window(hwnd):
    """Restore and bring a window to the front (works around the foreground lock)."""
    if not IS_WINDOWS or not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid and fg_tid != me and user32.AttachThreadInput(me, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_tid, False)
    return ok


def close_window(hwnd):
    return bool(IS_WINDOWS and hwnd and user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def edge_path():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None) or shutil.which("msedge")


def open_app_window(url, profile_dir, size=(440, 720)):
    """Open `url` as a compact app window. Returns 'edge' or 'browser' (fallback: normal tab)."""
    edge = edge_path() if IS_WINDOWS else None
    if edge:
        os.makedirs(profile_dir, exist_ok=True)
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profile_dir}", f"--window-size={size[0]},{size[1]}",
                          "--no-first-run", "--no-default-browser-check"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
        return "edge"
    import webbrowser
    webbrowser.open(url)
    return "browser"


TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:TM_TOAST_XML)
# The notifier's Setting property is not readable from Windows PowerShell 5.1, so check the
# documented user switches instead: all toasts off, or toasts off for this app.
$push = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications' -ErrorAction SilentlyContinue
if ($push -and $push.ToastEnabled -eq 0) { Write-Output 'disabled:all notifications are off in Windows Settings'; exit 3 }
$app = Get-ItemProperty ('HKCU:\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\' + $env:TM_TOAST_APPID) -ErrorAction SilentlyContinue
if ($app -and $app.Enabled -eq 0) { Write-Output 'disabled:notifications for Windows PowerShell are off in Windows Settings'; exit 3 }
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:TM_TOAST_APPID)
$notifier.Show([Windows.UI.Notifications.ToastNotification]::new($xml))
Write-Output 'shown'
"""


def toast_xml(title, body, url=None):
    launch = f" activationType=\"protocol\" launch={quoteattr(url)}" if url else ""
    return (f"<toast{launch}><visual><binding template=\"ToastGeneric\">"
            f"<text>{escape(title[:80])}</text><text>{escape(body[:200])}</text>"
            f"</binding></visual></toast>")


def show_toast(title, body, url=None, timeout=20):
    """Show a Windows toast. Returns (ok, detail). Clicking opens `url` (an http URL) when given."""
    if not IS_WINDOWS:
        return False, "Windows notifications need Windows"
    env = dict(os.environ, TM_TOAST_XML=toast_xml(title, body, url), TM_TOAST_APPID=POWERSHELL_AUMID)
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-Command", "-"], input=TOAST_SCRIPT, capture_output=True, text=True, env=env,
                             timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"could not run PowerShell: {e}"
    text = (out.stdout or "").strip()
    if out.returncode == 0 and text.endswith("shown"):
        return True, "shown"
    if text.startswith("disabled:"):
        return False, f"Windows notifications are turned off: {text.split(':', 1)[1]}"
    err = (out.stderr or text).strip().splitlines()
    return False, (err[-1] if err else f"PowerShell exited {out.returncode}")[:200]

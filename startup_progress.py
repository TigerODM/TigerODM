# Stdlib-only splash at Python startup via .pth
# - Windows: vraie fenêtre Win32 (ctypes), topmost, animée
# - macOS: petite fenêtre via AppleScript (osascript)
# Ferme quand une fenêtre Qt de CE PROCESS apparaît (ignore les autres processus).
# ENV:
#   STARTUP_SPLASH=0                -> désactive
#   STARTUP_SPLASH_TEXT="..."       -> texte
#   STARTUP_SPLASH_TIMEOUT=8        -> timeout de secours (s)
#   STARTUP_SPLASH_GRACE=0.3        -> délai avant fermeture après détection (s)
#   STARTUP_SPLASH_QT_CLASSES="..." -> Windows: classes Qt à reconnaître (ex: "Qt,Qt5,Qt6,QWidget")

import os, sys, time, atexit, threading, subprocess
import builtins

if not hasattr(builtins, "IsTiger"):
    builtins.IsTiger = False
ENABLED = os.environ.get("STARTUP_SPLASH", "1") != "0"
if builtins.IsTiger:
    TEXT = os.environ.get("STARTUP_SPLASH_TEXT", "Loading TigerODM environment...")
else:
    TEXT = os.environ.get("STARTUP_SPLASH_TEXT", "Loading ODM environment...")
_TIMEOUT_STR = os.environ.get("STARTUP_SPLASH_TIMEOUT", "360").strip()
TIMEOUT = float(_TIMEOUT_STR) if _TIMEOUT_STR else 0.0

_GRACE = float(os.environ.get("STARTUP_SPLASH_GRACE", "0.3"))
_QT_CLASSES = [s.strip() for s in os.environ.get(
    "STARTUP_SPLASH_QT_CLASSES",
    "Qt,Qt5,Qt6,QWidget,Qt5QWindowIcon,Qt6QWindowIcon"
).split(",") if s.strip()]

_stop_flag = False
_win_hwnd = None
_win_thread = None

def _is_windows(): return sys.platform.startswith("win")
def _is_macos():   return sys.platform == "darwin"

# ============================== Windows (Win32/ctypes) ==============================
def _win_show():
    """Thread UI: fenêtre topmost borderless avec barre indéterminée (Win32)."""
    import ctypes
    from ctypes import wintypes as _wt

    user32 = ctypes.windll.user32
    gdi32  = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    def _T(name, default): return getattr(_wt, name, default)

    HANDLE    = _T("HANDLE", ctypes.c_void_p)
    HWND      = _T("HWND", HANDLE)
    HINSTANCE = _T("HINSTANCE", HANDLE)
    HICON     = _T("HICON", HANDLE)
    HCURSOR   = _T("HCURSOR", HANDLE)
    HBRUSH    = _T("HBRUSH", HANDLE)
    HDC       = _T("HDC", HANDLE)
    HMENU     = _T("HMENU", HANDLE)
    UINT   = _T("UINT", ctypes.c_uint)
    INT    = _T("INT", ctypes.c_int)
    BOOL   = _T("BOOL", ctypes.c_int)
    LONG   = _T("LONG", ctypes.c_long)
    DWORD  = _T("DWORD", ctypes.c_uint32)
    WPARAM = _T("WPARAM", ctypes.c_size_t)
    LPARAM = _T("LPARAM", ctypes.c_ssize_t)
    LPCWSTR = _T("LPCWSTR", ctypes.c_wchar_p)
    LRESULT = getattr(_wt, "LRESULT", ctypes.c_ssize_t)

    class RECT(ctypes.Structure):
        _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]
    class POINT(ctypes.Structure):
        _fields_ = [("x", LONG), ("y", LONG)]
    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", HDC), ("fErase", BOOL), ("rcPaint", RECT),
                    ("fRestore", BOOL), ("fIncUpdate", BOOL),
                    ("rgbReserved", ctypes.c_ubyte * 32)]
    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", HWND), ("message", UINT), ("wParam", WPARAM),
                    ("lParam", LPARAM), ("time", DWORD), ("pt", POINT)]

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
    class WNDCLASS(ctypes.Structure):
        _fields_ = [("style", UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", INT),
                    ("cbWndExtra", INT), ("hInstance", HINSTANCE), ("hIcon", HICON),
                    ("hCursor", HCURSOR), ("hbrBackground", HBRUSH),
                    ("lpszMenuName", LPCWSTR), ("lpszClassName", LPCWSTR)]

    user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype  = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype  = ctypes.c_uint16
    user32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT,
                                       HWND, HMENU, HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype  = HWND
    user32.ShowWindow.argtypes = [HWND, INT]; user32.ShowWindow.restype  = BOOL
    user32.UpdateWindow.argtypes = [HWND];    user32.UpdateWindow.restype = BOOL
    user32.SetTimer.argtypes = [HWND, UINT, UINT, ctypes.c_void_p]; user32.SetTimer.restype = UINT
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT, UINT]; user32.PeekMessageW.restype = BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]; user32.TranslateMessage.restype = BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]; user32.DispatchMessageW.restype = LRESULT
    user32.BeginPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)]; user32.BeginPaint.restype = HDC
    user32.EndPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)];   user32.EndPaint.restype = BOOL
    user32.FillRect.argtypes = [HDC, ctypes.POINTER(RECT), HBRUSH];   user32.FillRect.restype = INT
    gdi32.CreateSolidBrush.argtypes = [DWORD]; gdi32.CreateSolidBrush.restype = HBRUSH
    gdi32.DeleteObject.argtypes = [HANDLE];    gdi32.DeleteObject.restype = BOOL
    gdi32.SetBkMode.argtypes = [HDC, INT];     gdi32.SetBkMode.restype = INT
    gdi32.SetTextColor.argtypes = [HDC, DWORD];gdi32.SetTextColor.restype = DWORD
    user32.DrawTextW.argtypes = [HDC, LPCWSTR, INT, ctypes.POINTER(RECT), UINT]; user32.DrawTextW.restype = INT
    user32.DestroyWindow.argtypes = [HWND]; user32.DestroyWindow.restype = BOOL
    user32.PostQuitMessage.argtypes = [INT]; user32.PostQuitMessage.restype = None
    user32.InvalidateRect.argtypes = [HWND, ctypes.c_void_p, BOOL]; user32.InvalidateRect.restype = BOOL
    user32.GetSystemMetrics.argtypes = [INT]; user32.GetSystemMetrics.restype = INT
    user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]; user32.PostMessageW.restype = BOOL
    kernel32.GetModuleHandleW.argtypes = [LPCWSTR]; kernel32.GetModuleHandleW.restype = HINSTANCE

    W, H = 360, 90
    WS_POPUP, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, SW_SHOW = 0x80000000, 0x00000008, 0x00000080, 5
    WM_DESTROY, WM_PAINT, WM_TIMER, WM_ERASEBKGND, WM_QUIT = 0x0002, 0x000F, 0x0113, 0x0014, 0x0012
    CS_HREDRAW, CS_VREDRAW = 0x0002, 0x0001
    DT_CENTER, DT_VCENTER, DT_SINGLELINE, TRANSPARENT = 0x00000001, 0x00000004, 0x00000020, 1
    PM_REMOVE = 0x0001
    COL_BG, COL_TEXT, COL_BAR_BG, COL_BAR_SEG = 0x202020, 0xE6E6E6, 0x404040, 0x00BFFF

    def RGB(c): return ((c & 0xFF) << 16) | (c & 0xFF00) | ((c >> 16) & 0xFF)
    state = {"pos": 0}

    def _fill_rect(hdc, rect, color):
        brush = gdi32.CreateSolidBrush(RGB(color))
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

    def _paint_bar(hdc, x, y, w, h, pos):
        seg_w = 60
        p = pos % (w + seg_w)
        left = max(0, p - seg_w); right = min(w, p)
        _fill_rect(hdc, RECT(x, y, x + w, y + h), COL_BAR_BG)
        if right > left:
            _fill_rect(hdc, RECT(x + left, y, x + right, y + h), COL_BAR_SEG)

    @WNDPROC
    def WndProc(hWnd, msg, wParam, lParam):
        if msg == WM_ERASEBKGND: return 1
        if msg == WM_PAINT:
            ps = PAINTSTRUCT(); hdc = user32.BeginPaint(hWnd, ctypes.byref(ps))
            _fill_rect(hdc, ps.rcPaint, COL_BG)
            gdi32.SetBkMode(hdc, TRANSPARENT); gdi32.SetTextColor(hdc, RGB(COL_TEXT))
            rect = RECT(0, 0, W, H)
            user32.DrawTextW(hdc, TEXT, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
            _paint_bar(hdc, 20, H - 28, W - 40, 10, state["pos"])
            user32.EndPaint(hWnd, ctypes.byref(ps)); return 0
        if msg == WM_TIMER:
            state["pos"] += 8; user32.InvalidateRect(hWnd, None, False); return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0); return 0
        return user32.DefWindowProcW(hWnd, msg, wParam, lParam)

    hInstance = kernel32.GetModuleHandleW(None)
    class_name = "PyStartupSplash"
    wc = WNDCLASS(); wc.style = CS_HREDRAW | CS_VREDRAW; wc.lpfnWndProc = WndProc
    wc.cbClsExtra = wc.cbWndExtra = 0; wc.hInstance = hInstance
    wc.hIcon = HICON(); wc.hCursor = HCURSOR(); wc.hbrBackground = HBRUSH()
    wc.lpszMenuName = None; wc.lpszClassName = class_name
    user32.RegisterClassW(ctypes.byref(wc))

    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    x, y = (sw - W) // 2, (sh - H) // 2

    hWnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, class_name, "Python Startup",
                                  WS_POPUP, x, y, W, H, None, None, hInstance, None)
    if not hWnd: return

    global _win_hwnd; _win_hwnd = hWnd
    user32.ShowWindow(hWnd, SW_SHOW); user32.UpdateWindow(hWnd); user32.SetTimer(hWnd, 1, 50, None)

    msg = MSG()
    while not _stop_flag:
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT: break
            user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.01)
    try: user32.DestroyWindow(hWnd)
    except Exception: pass

def _win_start():
    import threading
    global _win_thread
    _win_thread = threading.Thread(target=_win_show, daemon=True); _win_thread.start()

def _win_stop():
    global _stop_flag; _stop_flag = True
    try:
        import ctypes; user32 = ctypes.windll.user32
        if _win_hwnd: user32.PostMessageW(_win_hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception: pass

# ============================== macOS (AppleScript) ==============================
MAC_APPLESCRIPT_TEMPLATE = r'''
set splashText to "__TEXT__"
tell application "System Events"
    set UI elements enabled to true
    try
        set screenBounds to bounds of window of desktop of application process "Finder"
    on error
        set screenBounds to {0, 0, 1440, 900}
    end try
    set sx to item 1 of screenBounds
    set sy to item 2 of screenBounds
    set sw to item 3 of screenBounds
    set sh to item 4 of screenBounds
    set W to 380
    set H to 90
    set px to (sx + (sw - W) / 2)
    set py to (sy + (sh - H) / 2)
    set splashWindow to make new window with properties {position:{px, py}, size:{W, H}, title:"Python Startup"}
    set splashWindow's visible to true
    set splashWindow's level to floating
    tell splashWindow
        set miniaturizable to false
        set closeable to false
        set resizable to false
    end tell
    make new static text at splashWindow with properties {position:{20, 20}, size:{W - 40, 24}, name:"label", value:splashText}
    make new UI element at splashWindow with properties {role:"AXGroup", position:{20, 52}, size:{W - 40, 10}, name:"barBG"}
end tell
'''

def _mac_start():
    try:
        script = MAC_APPLESCRIPT_TEMPLATE.replace("__TEXT__", TEXT.replace('"', '\\"'))
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _mac_stop():
    try:
        CLOSE = r'''
tell application "System Events"
    try
        repeat with w in (every window whose title is "Python Startup")
            try
                set w's visible to false
                try
                    perform action "AXPress" of (first button of w whose description is "close button")
                end try
            end try
        end repeat
    end try
end tell
'''
        subprocess.Popen(["osascript", "-e", CLOSE],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ============================== Window watcher (Qt, même PID) ==============================
def _wait_for_qt_window_and_close():
    if _is_windows():
        _win_wait_for_qt_window_and_close(_QT_CLASSES, _GRACE)
    elif _is_macos():
        _mac_wait_for_own_window_and_close(_GRACE)

# --- Windows: détecter une fenêtre Qt appartenant AU MÊME PROCESSUS ---
def _win_wait_for_qt_window_and_close(class_patterns, grace):
    import ctypes, os
    user32 = ctypes.windll.user32

    GetClassNameW = user32.GetClassNameW
    GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    GetClassNameW.restype  = ctypes.c_int

    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    GetWindowTextW.restype  = ctypes.c_int

    EnumWindows = user32.EnumWindows
    EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
    EnumWindows.restype  = ctypes.c_bool

    IsWindowVisible = user32.IsWindowVisible
    IsWindowVisible.argtypes = [ctypes.c_void_p]
    IsWindowVisible.restype  = ctypes.c_bool

    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    GetWindowThreadProcessId.restype  = ctypes.c_uint

    current_pid = os.getpid()
    pats = [p.lower() for p in class_patterns]

    def _exists():
        hit = (ctypes.c_bool * 1)(False)

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum(hwnd, lparam):
            if not IsWindowVisible(hwnd):
                return True
            # PID must match current process
            pid_out = ctypes.c_uint(0)
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
            if pid_out.value != current_pid:
                return True  # ignore other processes

            # class name must look like Qt
            cbuf = ctypes.create_unicode_buffer(256)
            GetClassNameW(hwnd, cbuf, 256)
            cname = cbuf.value.lower()
            for p in pats:
                if p and p in cname:
                    hit[0] = True
                    return False
            return True

        EnumWindows(_enum, None)
        return bool(hit[0])

    # si déjà là (rare), fermer
    if _exists():
        if grace > 0: time.sleep(grace)
        _stop_all(); return

    while not _stop_flag:
        if _exists():
            if grace > 0: time.sleep(grace)
            _stop_all(); return
        time.sleep(0.05)

# --- macOS: détecter une fenêtre appartenant AU MÊME PROCESSUS ---
def _mac_wait_for_own_window_and_close(grace):
    import subprocess, os
    pid = os.getpid()
    script = f'''
set targetPid to {pid}
tell application "System Events"
    try
        repeat with p in every process
            if (unix id of p) is targetPid then
                if (count of (windows of p)) > 0 then
                    return true
                end if
            end if
        end repeat
    on error
        return false
    end try
end tell
return false
'''.strip()

    def _exists():
        try:
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return out.stdout.strip().lower() == "true"
        except Exception:
            return False

    if _exists():
        if grace > 0: time.sleep(grace)
        _stop_all(); return

    while not _stop_flag:
        if _exists():
            if grace > 0: time.sleep(grace)
            _stop_all(); return
        time.sleep(0.08)

# ============================== Orchestration ==============================
def _start():
    if _is_windows():
        _win_start()
    elif _is_macos():
        _mac_start()

def _stop_all():
    global _stop_flag
    _stop_flag = True
    if _is_windows():
        _win_stop()
    elif _is_macos():
        _mac_stop()

def _profile_hook(_frame, _event, _arg):
    return  # on ne ferme plus sur __main__

def close_splash():
    _stop_all()

if ENABLED:
    try:
        _start()
        # Lancer le watcher : ferme quand une fenêtre Qt (de CE process) apparaît
        threading.Thread(target=_wait_for_qt_window_and_close, daemon=True).start()
    except Exception:
        pass

if ENABLED and TIMEOUT > 0:
    def _timeout_kill():
        time.sleep(TIMEOUT)
        _stop_all()
    threading.Thread(target=_timeout_kill, daemon=True).start()

atexit.register(_stop_all)

"""The program's icon in the system tray, through the Windows API, so no extra library is needed.

Everything here runs on a thread of its own, which is why its callbacks should only hand work over to the main window.
"""
import ctypes
import ctypes.wintypes as wt
import sys
import threading

WM_NULL, WM_DESTROY, WM_LBUTTONUP, WM_RBUTTONUP = 0x0000, 0x0002, 0x0202, 0x0205
WM_TRAY = 0x8000 + 1  # WM_APP + 1: the message the tray sends this window
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
MF_STRING = 0x0000
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
IDI_APPLICATION = 32512
ICON_ID = 1
WINDOW_CLASS = "SakuyaTray"
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", ctypes.c_wchar * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", ctypes.c_wchar * 256), ("uTimeoutOrVersion", wt.UINT), ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wt.HICON)]


class TrayIcon:
    """on_click runs on a left click. menu() returns (title, action) pairs for a right click, asked anew so a changed language shows."""

    def __init__(self, tooltip: str, on_click, menu):
        self.tooltip = tooltip
        self.on_click = on_click
        self.menu = menu
        self.hwnd = None
        self.added = False
        self.notice = None
        self.ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def remove(self) -> None:
        """Takes the icon off the tray at once. Left behind, it would linger until the mouse passes over it."""
        if self.added:
            self.added = False
            self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._icon_data()))

    def notify(self, title: str, text: str) -> None:
        """A notice from the tray: it takes no focus and goes away by itself. One given before the icon is up waits for it."""
        self.notice = title, text
        if self.added:
            self._send_notice()

    def _send_notice(self) -> None:
        notice, self.notice = self.notice, None
        if notice:
            data = self._icon_data()
            data.uFlags = NIF_INFO
            data.szInfoTitle, data.szInfo = notice[0][:63], notice[1][:255]
            self.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def handle_event(self, event: int) -> None:
        if event == WM_LBUTTONUP:
            self.on_click()
        elif event == WM_RBUTTONUP:
            self._show_menu()

    def _libraries(self) -> None:
        # Own copies of the libraries: argument types set here must not change how the rest of the program calls them.
        self.user32 = user32 = ctypes.WinDLL("user32")
        self.shell32 = shell32 = ctypes.WinDLL("shell32")
        self.kernel32 = kernel32 = ctypes.WinDLL("kernel32")
        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
        user32.RegisterClassW.restype = wt.ATOM
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
        user32.RegisterWindowMessageW.argtypes = (wt.LPCWSTR,)
        user32.RegisterWindowMessageW.restype = wt.UINT
        user32.LoadIconW.restype = wt.HICON
        user32.LoadIconW.argtypes = (wt.HINSTANCE, wt.LPVOID)
        user32.CreatePopupMenu.restype = wt.HMENU
        user32.AppendMenuW.argtypes = (wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR)
        user32.TrackPopupMenu.argtypes = (wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID)
        user32.DestroyMenu.argtypes = (wt.HMENU,)
        user32.SetForegroundWindow.argtypes = (wt.HWND,)
        user32.PostMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
        user32.TranslateMessage.argtypes = (ctypes.POINTER(wt.MSG),)
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(wt.MSG),)
        user32.DispatchMessageW.restype = LRESULT
        shell32.Shell_NotifyIconW.argtypes = (wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
        shell32.Shell_NotifyIconW.restype = wt.BOOL
        shell32.ExtractIconW.restype = wt.HICON
        shell32.ExtractIconW.argtypes = (wt.HINSTANCE, wt.LPCWSTR, wt.UINT)
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        kernel32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)

    def _load_icon(self, instance) -> int:
        """The picture built into the exe. The value 1 means the file has no icon, as when running from source."""
        if getattr(sys, "frozen", False):
            icon = self.shell32.ExtractIconW(instance, sys.executable, 0)
            if icon and icon != 1:
                return icon
        return self.user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _icon_data(self) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=ICON_ID, uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY, hIcon=self.icon)
        data.szTip = self.tooltip[:127]
        return data

    def _add_icon(self) -> None:
        self.added = bool(self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._icon_data())))
        if self.added:
            self._send_notice()

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_TRAY:
            self.handle_event(lparam & 0xFFFF)
            return 0
        if message == self.taskbar_created:  # Explorer restarted and forgot every tray icon
            self._add_icon()
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        entries = self.menu()
        menu = self.user32.CreatePopupMenu()
        for number, (title, _) in enumerate(entries, 1):
            self.user32.AppendMenuW(menu, MF_STRING, number, title)
        point = wt.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        self.user32.SetForegroundWindow(self.hwnd)  # otherwise the menu stays open after a click elsewhere
        chosen = self.user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y, 0, self.hwnd, None)
        self.user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        self.user32.DestroyMenu(menu)
        if chosen:
            entries[chosen - 1][1]()

    def _run(self) -> None:
        self._libraries()
        instance = self.kernel32.GetModuleHandleW(None)
        self.procedure = WNDPROC(self._window_proc)  # kept here, because Windows calls it for as long as the window lives
        self.taskbar_created = self.user32.RegisterWindowMessageW("TaskbarCreated")
        window_class = WNDCLASSW(lpfnWndProc=self.procedure, hInstance=instance, lpszClassName=WINDOW_CLASS)
        self.user32.RegisterClassW(ctypes.byref(window_class))
        self.hwnd = self.user32.CreateWindowExW(0, WINDOW_CLASS, WINDOW_CLASS, 0, 0, 0, 0, 0, None, None, instance, None)
        self.icon = self._load_icon(instance)
        self._add_icon()
        self.ready.set()
        message = wt.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

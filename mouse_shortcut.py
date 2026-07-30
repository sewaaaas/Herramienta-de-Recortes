import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal


log = logging.getLogger("recortes")
IS_WINDOWS = sys.platform == "win32"

WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
VK_CODES = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}


class GlobalMouseShortcut(QObject):
    activated = pyqtSignal()
    installation_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._thread_id = 0
        self._hook = None
        self._callback_ref = None
        self._enabled = False
        self._modifier = "ctrl"
        self._suspended = False
        self._shortcut_active = False
        self._last_activation = 0.0
        self._ready = threading.Event()
        self._start_error = None
        self._lock = threading.RLock()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def set_suspended(self, suspended):
        self._suspended = bool(suspended)

    def update_configuration(self, enabled, modifier):
        modifier = str(modifier).lower()
        if modifier not in VK_CODES:
            modifier = "ctrl"
        self.stop()
        self._enabled = bool(enabled)
        self._modifier = modifier
        if not self._enabled:
            return True, None
        return self.start()

    def start(self):
        if not IS_WINDOWS:
            return False, "El hook global del mouse solo esta disponible en Windows."
        with self._lock:
            if self.running:
                return True, None
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._message_loop, name="ShotFlowMouseHook")
            self._thread.start()
        if not self._ready.wait(3.0):
            self.stop()
            return False, "El hilo del hook no respondio durante el inicio."
        if self._start_error:
            error = self._start_error
            self.stop()
            return False, error
        return True, None

    def stop(self):
        with self._lock:
            thread = self._thread
            thread_id = self._thread_id
        if thread is None:
            self._shortcut_active = False
            return True
        if thread_id and IS_WINDOWS:
            if not ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
                code = ctypes.get_last_error()
                log.error("No se pudo enviar WM_QUIT al hook. Error %s: %s", code, ctypes.FormatError(code))
        if thread is not threading.current_thread():
            thread.join(3.0)
        alive = thread.is_alive()
        if alive:
            log.error("El hilo del hook de mouse no termino dentro del plazo")
        else:
            with self._lock:
                if self._thread is thread:
                    self._thread = None
        self._shortcut_active = False
        return not alive

    def _message_loop(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = ctypes.c_ssize_t
        hook_proc_type = ctypes.WINFUNCTYPE(lresult, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_proc_type, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = lresult
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def callback(code, w_param, l_param):
            if code >= 0 and not self._suspended:
                message = int(w_param)
                if message == WM_RBUTTONDOWN:
                    key_down = bool(user32.GetAsyncKeyState(VK_CODES[self._modifier]) & 0x8000)
                    if key_down and not self._shortcut_active:
                        self._shortcut_active = True
                        return 1
                elif message == WM_RBUTTONUP and self._shortcut_active:
                    self._shortcut_active = False
                    now = time.monotonic()
                    if now - self._last_activation >= 0.25:
                        self._last_activation = now
                        self.activated.emit()
                    return 1
            return user32.CallNextHookEx(self._hook, code, w_param, l_param)

        message = wintypes.MSG()
        self._thread_id = kernel32.GetCurrentThreadId()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_NOREMOVE)
        self._callback_ref = hook_proc_type(callback)
        ctypes.set_last_error(0)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._callback_ref, None, 0)
        if not self._hook:
            code = ctypes.get_last_error()
            detail = ctypes.FormatError(code).strip() if code else "Windows no proporciono detalles."
            self._start_error = f"Error de Windows {code}: {detail}"
            log.error("No se pudo instalar WH_MOUSE_LL. %s", self._start_error)
            self._ready.set()
            self._thread_id = 0
            return

        log.info("Hook global de mouse instalado para %s + clic derecho", self._modifier)
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            hook, self._hook = self._hook, None
            if hook and not user32.UnhookWindowsHookEx(hook):
                code = ctypes.get_last_error()
                log.error("No se pudo desinstalar el hook. Error %s: %s", code, ctypes.FormatError(code))
            else:
                log.info("Hook global de mouse desinstalado")
            self._thread_id = 0
            self._callback_ref = None
            self._shortcut_active = False


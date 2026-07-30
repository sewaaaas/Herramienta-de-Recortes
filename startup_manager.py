import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import winreg
else:
    winreg = None


log = logging.getLogger("recortes")


class StartupManager:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "ShotFlow"

    def __init__(self, script_path):
        self.script_path = Path(script_path).resolve()

    def expected_startup_command(self):
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'

        executable = Path(sys.executable).resolve()
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
        else:
            log.warning("pythonw.exe no existe; el inicio automatico podria mostrar una consola")
        return f'"{executable}" "{self.script_path}"'

    def registered_command(self):
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, self.VALUE_NAME)
                return str(value)
        except FileNotFoundError:
            return None

    def is_startup_enabled(self):
        registered = self.registered_command()
        expected = self.expected_startup_command()
        enabled = registered == expected
        if registered is not None and not enabled:
            log.warning(
                "Entrada de inicio ShotFlow desactualizada. Registrada=%r Esperada=%r",
                registered,
                expected,
            )
        return enabled

    def enable_startup(self):
        if winreg is None:
            raise OSError("El inicio automatico solo esta disponible en Windows")
        expected = self.expected_startup_command()
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ
        ) as key:
            winreg.SetValueEx(key, self.VALUE_NAME, 0, winreg.REG_SZ, expected)
        if self.registered_command() != expected:
            raise OSError("Windows no confirmo el comando de inicio automatico")
        log.info("Inicio automatico habilitado: %s", expected)
        return True

    def disable_startup(self):
        if winreg is None:
            raise OSError("El inicio automatico solo esta disponible en Windows")
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ
            ) as key:
                try:
                    winreg.DeleteValue(key, self.VALUE_NAME)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        if self.registered_command() is not None:
            raise OSError("Windows conserva el valor ShotFlow despues de eliminarlo")
        log.info("Inicio automatico deshabilitado")
        return True


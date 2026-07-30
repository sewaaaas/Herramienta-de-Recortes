import logging

from PyQt6.QtCore import QSettings


log = logging.getLogger("recortes")


class SettingsManager:
    ORGANIZATION = "ShotFlow"
    APPLICATION = "ShotFlow"
    DEFAULTS = {
        "mouse_shortcut/enabled": False,
        "mouse_shortcut/modifier": "ctrl",
        "startup/enabled": False,
        "notifications/show_on_startup": True,
    }
    VALID_MODIFIERS = {"ctrl", "alt", "shift"}

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)
        self._apply_defaults_and_validate()
        log.info("Configuracion cargada desde %s", self._settings.fileName())

    @staticmethod
    def _as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return default

    def _apply_defaults_and_validate(self):
        changed = False
        for key, default in self.DEFAULTS.items():
            if not self._settings.contains(key):
                self._settings.setValue(key, default)
                changed = True

        modifier = str(self._settings.value("mouse_shortcut/modifier", "ctrl")).strip().lower()
        if modifier not in self.VALID_MODIFIERS:
            log.warning(
                "Valor invalido para mouse_shortcut/modifier (%r); se sustituye por 'ctrl'",
                modifier,
            )
            self._settings.setValue("mouse_shortcut/modifier", "ctrl")
            changed = True

        if changed:
            self._settings.sync()

    def get(self, key, default=None):
        fallback = self.DEFAULTS.get(key, default)
        value = self._settings.value(key, fallback)
        if isinstance(fallback, bool):
            return self._as_bool(value, fallback)
        return value

    def get_bool(self, key):
        return self._as_bool(self._settings.value(key, self.DEFAULTS.get(key, False)))

    def set(self, key, value, sync=True):
        if key == "mouse_shortcut/modifier":
            value = str(value).strip().lower()
            if value not in self.VALID_MODIFIERS:
                log.warning("Modificador invalido %r; se guarda 'ctrl'", value)
                value = "ctrl"
        if key in self.DEFAULTS and isinstance(self.DEFAULTS[key], bool):
            value = self._as_bool(value, self.DEFAULTS[key])
        self._settings.setValue(key, value)
        if sync:
            self._settings.sync()
        log.info("Preferencia modificada: %s=%r", key, value)

    def sync(self):
        self._settings.sync()


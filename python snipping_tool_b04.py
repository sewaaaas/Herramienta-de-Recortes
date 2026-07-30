import ctypes
import logging
import math
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QAbstractNativeEventFilter, QPoint, QPointF, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QRegion
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)


APP_DIR = Path(__file__).resolve().parent
LOG_FILE = APP_DIR / "herramienta_recortes.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("recortes")

IS_WINDOWS = sys.platform == "win32"
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_SNAPSHOT = 0x2C
VK_S = 0x53
HOTKEY_PRINT = 1
HOTKEY_CTRL_SHIFT_S = 2


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.UnregisterHotKey.restype = wintypes.BOOL


def draw_arrow(painter, start, end, color, width=3):
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(color)
    painter.drawLine(start, end)
    dx, dy = end.x() - start.x(), end.y() - start.y()
    if dx == 0 and dy == 0:
        return
    angle = math.atan2(dy, dx)
    size = max(10, width * 4)
    opening = math.radians(28)
    p1 = QPointF(end.x() - size * math.cos(angle - opening), end.y() - size * math.sin(angle - opening))
    p2 = QPointF(end.x() - size * math.cos(angle + opening), end.y() - size * math.sin(angle + opening))
    painter.drawPolygon(QPolygonF([QPointF(end), p1, p2]))


def render_shape(painter, tool, start, end, color, width=3):
    if tool == "rectangle":
        painter.setPen(QPen(color, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRect(start, end).normalized())
    elif tool == "arrow":
        draw_arrow(painter, start, end, color, width)


def create_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#0878d1"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(3, 3, 58, 58)
    painter.setPen(QPen(QColor("white"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
    painter.drawLine(19, 17, 19, 31)
    painter.drawLine(19, 17, 33, 17)
    painter.drawLine(45, 33, 45, 47)
    painter.drawLine(45, 47, 31, 47)
    painter.end()
    return QIcon(pixmap)


class HotkeyFilter(QAbstractNativeEventFilter):
    """Recibe WM_HOTKEY a nivel del hilo; no necesita una ventana oculta."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = []

    def register_all(self):
        if not IS_WINDOWS:
            log.warning("Los atajos globales solo están disponibles en Windows")
            return
        self._register(HOTKEY_PRINT, MOD_NOREPEAT, VK_SNAPSHOT, "Impr Pant")
        self._register(
            HOTKEY_CTRL_SHIFT_S,
            MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
            VK_S,
            "Ctrl+Shift+S",
        )

    def _register(self, hotkey_id, modifiers, key, name):
        ctypes.set_last_error(0)
        # HWND=None registra el atajo en la cola del hilo actual.
        if user32.RegisterHotKey(None, hotkey_id, modifiers, key):
            self.registered.append(hotkey_id)
            log.info("Atajo registrado: %s", name)
        else:
            code = ctypes.get_last_error()
            log.error("No se pudo registrar %s. Error %s: %s", name, code, ctypes.FormatError(code).strip())

    def nativeEventFilter(self, event_type, message):
        if IS_WINDOWS:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and int(msg.wParam) in self.registered:
                # Se agenda para no crear ventanas dentro del despacho nativo.
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

    def unregister_all(self):
        if IS_WINDOWS:
            for hotkey_id in self.registered:
                user32.UnregisterHotKey(None, hotkey_id)
        self.registered.clear()


class FloatingToolbar(QWidget):
    COLORS = ("#e74c3c", "#2ecc71", "#3498db", "#f1c40f", "#000000", "#ffffff")

    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        group = QButtonGroup(self)
        group.setExclusive(True)
        rect = QPushButton("▭")
        arrow = QPushButton("➜")
        for button in (rect, arrow):
            button.setCheckable(True)
            group.addButton(button)
            layout.addWidget(button)
        rect.setToolTip("Rectángulo")
        arrow.setToolTip("Flecha")
        rect.clicked.connect(lambda: setattr(overlay, "current_tool", "rectangle"))
        arrow.clicked.connect(lambda: setattr(overlay, "current_tool", "arrow"))

        self.color_buttons = []
        for color in self.COLORS:
            button = QPushButton()
            button.setFixedSize(20, 20)
            button.clicked.connect(lambda checked=False, c=color: self.select_color(c))
            self.color_buttons.append(button)
            layout.addWidget(button)
        self.select_color(overlay.current_color.name())

        copy_button = QPushButton("Copiar")
        save_button = QPushButton("Guardar")
        copy_button.clicked.connect(overlay.copy_and_close)
        save_button.clicked.connect(self.save)
        layout.addWidget(copy_button)
        layout.addWidget(save_button)
        self.setStyleSheet(
            "QWidget{background:#292929;border-radius:6px}"
            "QPushButton{background:#414141;color:white;border:0;padding:6px 10px;border-radius:4px}"
            "QPushButton:hover{background:#555} QPushButton:checked{background:#0878d1}"
        )

    def select_color(self, color):
        self.overlay.current_color = QColor(color)
        for button, value in zip(self.color_buttons, self.COLORS):
            border = "3px solid white" if value == color else "2px solid #888"
            button.setStyleSheet(f"background:{value};border:{border};border-radius:10px;padding:0")

    def save(self):
        default = f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar captura", default, "PNG (*.png)")
        if filename and self.overlay.final_pixmap().save(filename, "PNG"):
            self.overlay.close_session()


class Overlay(QWidget):
    def __init__(self, screen, controller):
        super().__init__()
        self.controller = controller
        self.dpr = screen.devicePixelRatio()
        self.background = screen.grabWindow(0)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.selecting = False
        self.origin = None
        self.selection = QRect()
        self.capture = None
        self.toolbar = None
        self.current_tool = None
        self.current_color = QColor("#e74c3c")
        self.annotations = []
        self.drawing = False
        self.shape_start = None
        self.shape_end = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self.background)
        shade = QColor(0, 0, 0, 105)
        if not self.selection.isValid():
            painter.fillRect(self.rect(), shade)
            return
        dark = QRegion(self.rect()).subtracted(QRegion(self.selection))
        painter.setClipRegion(dark)
        painter.fillRect(self.rect(), shade)
        painter.setClipRegion(QRegion(self.rect()))
        painter.setPen(QPen(QColor("#0878d1"), 2))
        painter.drawRect(self.selection)
        painter.setClipRect(self.selection)
        for shape in self.annotations:
            render_shape(painter, shape[0], shape[1], shape[2], shape[3])
        if self.drawing:
            render_shape(painter, self.current_tool, self.shape_start, self.shape_end, self.current_color)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if not self.selection.isValid():
            self._start_selection(pos)
        elif self.selection.contains(pos) and self.current_tool:
            self.drawing = True
            self.shape_start = self.shape_end = pos
        elif not self.selection.contains(pos):
            self._reset()
            self._start_selection(pos)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.selecting:
            self.selection = QRect(self.origin, pos).normalized()
            self.update()
        elif self.drawing:
            self.shape_end = pos
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self.selecting:
            self.selecting = False
            self.selection = QRect(self.origin, pos).normalized()
            if self.selection.width() < 10 or self.selection.height() < 10:
                self.selection = QRect()
                self.update()
                return
            self._capture_selection()
            self._show_toolbar()
            self.update()
        elif self.drawing:
            self.drawing = False
            self.shape_end = pos
            if abs(pos.x() - self.shape_start.x()) > 3 or abs(pos.y() - self.shape_start.y()) > 3:
                self.annotations.append((self.current_tool, self.shape_start, pos, QColor(self.current_color)))
            self.shape_start = self.shape_end = None
            self.update()

    def _start_selection(self, pos):
        self.origin = pos
        self.selection = QRect(pos, pos)
        self.selecting = True
        self.update()

    def _reset(self):
        if self.toolbar:
            self.toolbar.deleteLater()
        self.toolbar = None
        self.selection = QRect()
        self.capture = None
        self.annotations.clear()
        self.current_tool = None

    def _capture_selection(self):
        dpr = self.dpr
        rect = QRect(
            round(self.selection.x() * dpr), round(self.selection.y() * dpr),
            round(self.selection.width() * dpr), round(self.selection.height() * dpr),
        )
        self.capture = self.background.copy(rect)
        self.capture.setDevicePixelRatio(dpr)

    def _show_toolbar(self):
        self.toolbar = FloatingToolbar(self)
        self.toolbar.adjustSize()
        size = self.toolbar.size()
        x = min(max(0, self.selection.right() - size.width()), self.width() - size.width())
        y = self.selection.bottom() + 8
        if y + size.height() > self.height():
            y = self.selection.top() - size.height() - 8
        self.toolbar.move(x, max(0, y))
        self.toolbar.show()
        self.toolbar.raise_()

    def _pixmap_point(self, point):
        """Convierte coordenadas del overlay a coordenadas lógicas del recorte.

        QPainter conoce el devicePixelRatio del QPixmap y realiza por sí mismo
        la conversión de estas coordenadas lógicas a píxeles físicos. Multiplicar
        aquí por DPR desplazaría y agrandaría las anotaciones en pantallas con
        escala de 125 %, 150 %, etc.
        """
        origin = self.selection.topLeft()
        return QPoint(point.x() - origin.x(), point.y() - origin.y())

    def final_pixmap(self):
        result = self.capture.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # El ancho también se expresa en unidades lógicas; QPainter lo escala
        # según el DPR del pixmap de destino.
        width = 3
        for tool, start, end, color in self.annotations:
            render_shape(painter, tool, self._pixmap_point(start), self._pixmap_point(end), color, width)
        painter.end()
        return result

    def copy_and_close(self):
        if self.capture is not None:
            QApplication.clipboard().setPixmap(self.final_pixmap())
            self.close_session()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_session()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy_and_close()

    def close_session(self):
        self.controller.finish_capture()


class Controller:
    def __init__(self, app):
        self.app = app
        self.overlays = []
        self.capturing = False

        self.hotkeys = HotkeyFilter(self.take_capture)
        self.app.installNativeEventFilter(self.hotkeys)
        self.hotkeys.register_all()

        # Referencias persistentes: PyQt no debe recolectar menú ni acciones.
        self.tray = QSystemTrayIcon(create_icon(), self.app)
        self.tray.setToolTip("Herramienta de Recortes")
        self.menu = QMenu()
        self.action_capture = self.menu.addAction("Tomar recorte   (Impr Pant / Ctrl+Shift+S)")
        self.action_capture.triggered.connect(self.take_capture)
        self.menu.addSeparator()
        self.action_quit = self.menu.addAction("Salir")
        self.action_quit.triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        log.info("Icono solicitado. visible=%s, bandeja_disponible=%s", self.tray.isVisible(), QSystemTrayIcon.isSystemTrayAvailable())
        QTimer.singleShot(700, self._announce)

    def _announce(self):
        self.tray.showMessage(
            "Herramienta de Recortes activa",
            "Está en la bandeja. Usa Impr Pant o Ctrl+Shift+S.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.take_capture()

    def take_capture(self):
        if self.capturing:
            return
        self.capturing = True
        self.overlays = [Overlay(screen, self) for screen in QGuiApplication.screens()]
        for overlay in self.overlays:
            overlay.show()
            overlay.raise_()
        if self.overlays:
            self.overlays[0].activateWindow()
            self.overlays[0].setFocus()
        log.info("Captura iniciada en %s pantalla(s)", len(self.overlays))

    def finish_capture(self):
        overlays, self.overlays = self.overlays, []
        self.capturing = False
        for overlay in overlays:
            overlay.close()
            overlay.deleteLater()
        log.info("Captura finalizada; aplicación continúa en bandeja")

    def quit(self):
        self.finish_capture()
        self.hotkeys.unregister_all()
        self.app.removeNativeEventFilter(self.hotkeys)
        self.tray.hide()
        log.info("Aplicación cerrada")
        self.app.quit()


def main():
    log.info("Iniciando aplicación")
    app = QApplication(sys.argv)
    app.setApplicationName("Herramienta de Recortes")
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "Herramienta de Recortes",
            "Windows no informó una bandeja del sistema disponible.\n\n"
            f"Consulta el registro:\n{LOG_FILE}",
        )
        return 1
    # La referencia vive tanto en una variable local como en QApplication.
    controller = Controller(app)
    app.controller = controller
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("Error fatal")
        raise

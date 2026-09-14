"""Meeting Scratchpad HUD — always-on-top floating scratchpad.

Single-file PyQt6 + pynput app. Run with:  python hud.py
Requires: PyQt6, pynput  (see requirements.txt)
"""

from __future__ import annotations

import faulthandler
import html
import json
import re
import socket
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

VAULT_FILE = Path.home() / "workspace" / "notes_vault" / "stream_notes.jsonl"
ERROR_LOG = Path.home() / "workspace" / "notes_vault" / "hud_errors.log"
TAG_RE = re.compile(r"(#\w+)")
TAG_COLOR = "#4EC9B0"
# Input limits: soft cap asks for confirmation (likely accidental paste),
# hard cap truncates outright at the widget level.
SOFT_MAX_NOTE_CHARS = 2000
HARD_MAX_NOTE_CHARS = 10000


def log_exception(where: str) -> None:
    """Log slot exceptions to stderr + file instead of aborting (PyQt6 qFatals)."""
    text = f"[hud:{where}] unhandled exception:\n{traceback.format_exc()}"
    print(text, file=sys.stderr)
    _append_log(text)


def _append_log(text: str) -> None:
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().astimezone().isoformat()} {text}\n")
    except Exception:
        pass


def macos_accessibility_trusted() -> bool | None:
    """None off-macOS; otherwise whether the key-tap grant is in place."""
    if sys.platform != "darwin":
        return None
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def safe_slot(fn):
    """Decorator: never let a Qt slot propagate (PyQt6 aborts the process)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log_exception(fn.__qualname__)
            return None

    return wrapper

BASE_STYLE = """
ScratchpadHUD {
    background: transparent;
    border: none;
}
#headerBar {
    background: transparent;
}
QLabel#dot {
    color: #4EC9B0;
    font-size: 10px;
    background: transparent;
    border: none;
}
QLabel#dot[alert="true"] {
    color: #E57373;
}
QLabel {
    color: #B0B0B5;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    background: transparent;
    border: none;
}
QLabel#sessionLabel {
    color: #8E8E93;
    font-family: "SF Mono", "Cascadia Code", Consolas, monospace;
    font-size: 12px;
}
QTextEdit#feed {
    background-color: #15151B;
    border: 1px solid #2E2E33;
    border-radius: 6px;
    color: #E4E4E7;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    selection-background-color: #3E3E42;
}
QLineEdit#input {
    background-color: #101014;
    border: 1px solid #3E3E42;
    border-radius: 6px;
    color: #F4F4F5;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 13px;
    padding: 7px 10px;
    selection-background-color: #4EC9B0;
    selection-color: #1A1A1E;
}
QLineEdit#input:focus {
    border: 1px solid #4EC9B0;
}
QPushButton#endBtn {
    background-color: #3A2A2C;
    border: 1px solid #5A3A3E;
    border-radius: 10px;
    color: #E8A0A3;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 11px;
    padding: 3px 12px;
}
QPushButton#endBtn:hover {
    background-color: #573338;
    color: #FFB4B6;
}
QPushButton#hideBtn {
    background-color: transparent;
    border: 1px solid #3E3E42;
    border-radius: 10px;
    color: #8E8E93;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 11px;
    padding: 3px 10px;
}
QPushButton#hideBtn:hover {
    color: #E4E4E7;
    border: 1px solid #5A5A5E;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #5A5A5E;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QMessageBox {
    background-color: #1A1A1E;
}
QMessageBox QLabel {
    color: #E4E4E7;
}
QLabel#confirmTitle {
    color: #F4F4F5;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 13px;
    font-weight: bold;
    background: transparent;
    border: none;
}
QLabel#confirmBody {
    color: #B0B0B5;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    background: transparent;
    border: none;
}
QPushButton#dangerBtn {
    background-color: #573338;
    border: 1px solid #7A444A;
    border-radius: 8px;
    color: #FFB4B6;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    padding: 6px 14px;
}
QPushButton#dangerBtn:hover {
    background-color: #6B3E44;
}
QPushButton#ghostBtn {
    background-color: transparent;
    border: 1px solid #3E3E42;
    border-radius: 8px;
    color: #B0B0B5;
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
    padding: 6px 14px;
}
QPushButton#ghostBtn:hover {
    color: #E4E4E7;
    border: 1px solid #5A5A5E;
}
"""


def session_id_now(now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    return now.strftime("sess_%Y%m%d_%H%M%S")


def append_jsonl(record: dict) -> None:
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with VAULT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def render_note_html(timestamp: datetime, raw: str) -> str:
    time_prefix = timestamp.strftime("%H:%M:%S")
    safe = html.escape(raw)
    highlighted = TAG_RE.sub(
        rf'<span style="color:{TAG_COLOR}; font-weight:bold;">\1</span>', safe
    )
    return (
        f'<div style="margin-bottom:2px;">'
        f'<span style="color:#71717A;">[{time_prefix}]</span> '
        f'<span style="color:#E4E4E7;">{highlighted}</span>'
        f"</div>"
    )


class HotkeyBridge(QObject):
    """Thread-safe bridge: background threads emit, Qt slots run on UI thread."""

    toggle_requested = pyqtSignal()
    activate_requested = pyqtSignal()


class SingleInstance:
    """One primary HUD per login session (stdlib Unix socket, no extra deps).

    A second launch nudges the primary to the front and exits immediately,
    so two copies can never append to the vault or fight over the hotkey.
    """

    def __init__(self, name: str = "meetinghud.sock") -> None:
        self.path = f"{tempfile.gettempdir()}/{name}"
        self.sock: socket.socket | None = None
        self.is_primary = False
        self.on_activate = None  # Callable[[], None] | None, set after UI exists

    def acquire(self) -> bool:
        """True if this process is primary; else notify primary, return False."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.bind(self.path)
        except OSError:
            if self._notify_primary():
                return False
            # Stale socket file (previous crash): take over with a fresh fd.
            try:
                Path(self.path).unlink()
            except OSError:
                pass
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.bind(self.path)
            except OSError:
                # Still bound (racy sibling) — bow out quietly.
                print("[hud] another instance is running.", file=sys.stderr)
                return False
        self.sock.listen(1)
        self.is_primary = True
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def _notify_primary(self) -> bool:
        """Ping the primary and require an ack; ghosts don't ack."""
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(self.path)
            s.sendall(b"show")
            ack = s.recv(2)
            s.close()
            return ack == b"ok"
        except OSError:
            return False

    def _serve(self) -> None:
        assert self.sock is not None
        while True:
            try:
                conn, _ = self.sock.accept()
                try:
                    conn.recv(16)
                    conn.sendall(b"ok")
                except OSError:
                    pass
                finally:
                    conn.close()
                if self.on_activate is not None:
                    try:
                        self.on_activate()
                    except Exception:
                        pass
            except OSError:
                return


class ConfirmDialog(QDialog):
    """Frameless dark confirm dialog matching the HUD aesthetic."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        body: str,
        confirm_text: str = "End Session",
        cancel_text: str = "Keep Writing",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedSize(320, 170)
        self.setStyleSheet(BASE_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("confirmTitle")
        root.addWidget(title_lbl)

        info = QLabel(body)
        info.setObjectName("confirmBody")
        root.addWidget(info, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        keep_btn = QPushButton(cancel_text)
        keep_btn.setObjectName("ghostBtn")
        keep_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        keep_btn.clicked.connect(self.reject)
        row.addWidget(keep_btn)
        end_btn = QPushButton(confirm_text)
        end_btn.setObjectName("dangerBtn")
        end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        end_btn.setDefault(True)
        end_btn.clicked.connect(self.accept)
        row.addWidget(end_btn)
        root.addLayout(row)

    @safe_slot
    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(30, 30, 36, 245))
        painter.setPen(QPen(QColor("#3E3E42"), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)


class ScratchpadHUD(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ScratchpadHUD")
        self.session_id: str = ""
        self.session_start: datetime | None = None
        self.note_count: int = 0
        self._drag_pos: object = None  # QPoint | None (kept untyped for Qt6 compat)
        self._flash: bool = False  # red-border reset confirmation (painted)
        self._save_ok: bool = True  # False after a failed vault write (red dot)
        self._hotkey_ok: bool | None = None  # False while key-tap grant missing
        self._hotkey_listener = None
        self._hotkey_thread: threading.Thread | None = None
        self._trust_timer: QTimer | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(420, 300)
        self.setMinimumSize(320, 220)

        # Thread-safe bridge for background threads (hotkey tap, 2nd instance).
        self._bridge = HotkeyBridge(self)
        self._bridge.toggle_requested.connect(self.toggle_visibility)
        self._bridge.activate_requested.connect(self._force_show)

        self._build_ui()
        self._apply_style()
        self.new_session()
        self._start_global_hotkeys()
        self._wire_shortcuts()
        self._build_tray()
        self._start_space_watcher()

    # -- UI ---------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        # Header bar: dedicated drag-handle container + timer + End Session.
        # A real QWidget (not a bare layout) so the whole strip grabs drags.
        self.header = QWidget()
        self.header.setObjectName("headerBar")
        self.header.setFixedHeight(32)
        self.header.setCursor(Qt.CursorShape.OpenHandCursor)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)

        self.dot = QLabel("●")
        self.dot.setObjectName("dot")
        header.addWidget(self.dot)

        self.session_label = QLabel("--:--")
        self.session_label.setObjectName("sessionLabel")
        self.session_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self.session_label, stretch=1)

        self.end_btn = QPushButton("End Session")
        self.end_btn.setObjectName("endBtn")
        self.end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.end_btn.setToolTip("Seal session & clear (Ctrl+Shift+E)")
        self.end_btn.clicked.connect(self.confirm_end_session)
        header.addWidget(self.end_btn)

        self.hide_btn = QPushButton("Hide")
        self.hide_btn.setObjectName("hideBtn")
        self.hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_btn.setToolTip("Hide HUD — session keeps running (hotkey/Esc)")
        # QWidget.hide is a C++ slot: Qt drops the extra clicked(bool) arg.
        self.hide_btn.clicked.connect(self.hide)
        header.addWidget(self.hide_btn)
        root.addWidget(self.header)

        # Drag from anywhere on the header strip except the button.
        for grabber in (self.header, self.dot, self.session_label):
            grabber.installEventFilter(self)

        # Active session feed
        self.feed = QTextEdit()
        self.feed.setObjectName("feed")
        self.feed.setReadOnly(True)
        self.feed.setPlaceholderText("No notes yet this session…")
        root.addWidget(self.feed, stretch=1)

        # Input bar (hard cap: absurd pastes truncated, soft cap warns in add_note)
        self.input = QLineEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText("Add thought (#todo, #concept)... [Enter]")
        self.input.setMaxLength(HARD_MAX_NOTE_CHARS)
        self.input.returnPressed.connect(self.add_note)
        root.addWidget(self.input)

    def _build_tray(self) -> None:
        """Menu-bar tray icon: the exit hatch for a dock-less agent app.

        Single click toggles the HUD; right-click offers Show/Hide + Quit.
        Without this, a hidden HUD can never be quit except via kill.
        """
        self.tray = None
        self.tray_show_action = None
        self.tray_quit_action = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("[hud] system tray unavailable; no tray icon", file=sys.stderr)
            return
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor("#4EC9B0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()

        self.tray = QSystemTrayIcon(QIcon(pm), self)
        self.tray.setToolTip("MeetingHUD — meeting scratchpad")
        menu = QMenu()
        # QAction.triggered passes checked(bool); toggle_visibility accepts it.
        self.tray_show_action = menu.addAction("Show / Hide")
        self.tray_show_action.triggered.connect(self.toggle_visibility)
        menu.addSeparator()
        self.tray_quit_action = menu.addAction("Quit MeetingHUD")
        app = QApplication.instance()
        if app is not None:
            # QApplication.quit is a C++ slot: extra triggered(bool) arg dropped.
            self.tray_quit_action.triggered.connect(app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    @safe_slot
    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def _start_space_watcher(self) -> None:
        """Follow the active screen when the user swipes Spaces (macOS).

        Without this, a visible HUD stays parked on the old display while
        you work fullscreen on another one. Only acts while visible, so a
        hidden HUD never jumps around behind your back.
        """
        self._space_observer = None
        if sys.platform != "darwin":
            return
        try:
            from Cocoa import NSObject
            from Foundation import NSWorkspace
        except Exception as exc:
            print(f"[hud] space watcher unavailable: {exc}", file=sys.stderr)
            return

        hud = self

        class _SpaceObserver(NSObject):
            def activeSpaceChanged_(self, _note) -> None:
                try:
                    if hud.isVisible():
                        hud._move_to_active_screen()
                except Exception:
                    pass

        try:
            observer = _SpaceObserver.alloc().init()
            (
                NSWorkspace.sharedWorkspace()
                .notificationCenter()
                .addObserver_selector_name_object_(
                    observer,
                    "activeSpaceChanged:",
                    "NSWorkspaceActiveSpaceDidChangeNotification",
                    None,
                )
            )
            self._space_observer = observer  # keep alive
        except Exception as exc:
            print(f"[hud] space watcher failed: {exc}", file=sys.stderr)

    def _apply_style(self) -> None:
        # Window backdrop + border are painted in paintEvent (reliable with
        # WA_TranslucentBackground on macOS); QSS only styles children.
        self.setStyleSheet(BASE_STYLE)

    def _wire_shortcuts(self) -> None:
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self.hide)

        end = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        end.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(self.confirm_end_session)

        quit_sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Quit), self)
        quit_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_sc.activated.connect(QApplication.instance().quit)

    # -- Opaque backdrop (reliable on macOS translucent windows) ------------
    @safe_slot
    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._flash:
            painter.setBrush(QColor(46, 24, 26, 245))
            painter.setPen(QPen(QColor("#E57373"), 2))
        else:
            painter.setBrush(QColor(24, 24, 29, 242))
            painter.setPen(QPen(QColor("#3E3E42"), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)

    # -- Drag (header strip via event filter + blank padding fallback) ------
    def _drag_start(self, global_pos) -> None:
        self._drag_pos = global_pos - self.frameGeometry().topLeft()

    def _drag_to(self, global_pos) -> None:
        if self._drag_pos is not None:
            self.move(global_pos - self._drag_pos)  # type: ignore[operator]

    def eventFilter(self, obj, event) -> bool:  # noqa: N802, ANN001
        try:
            if event is None:
                return False
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and (
                event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag_start(event.globalPosition().toPoint())
                return True
            if etype == QEvent.Type.MouseMove and (
                event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._drag_to(event.globalPosition().toPoint())
                return True
            if etype == QEvent.Type.MouseButtonRelease:
                self._drag_pos = None
                return True
            return super().eventFilter(obj, event)
        except Exception:
            log_exception("ScratchpadHUD.eventFilter")
            return False

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            # Let interactive widgets keep their events; everything else drags.
            if isinstance(child, (QLineEdit, QPushButton, QTextEdit)):
                self._drag_pos = None
                return
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is None or self._drag_pos is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)  # type: ignore[operator]
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        self._drag_pos = None

    # -- Session lifecycle -------------------------------------------------
    @safe_slot
    def new_session(self) -> None:
        now = datetime.now().astimezone()
        self.session_id = session_id_now(now)
        self.session_start = now
        self.note_count = 0
        self.feed.clear()
        self.session_label.setText(self.session_id)

    def _set_save_state(self, ok: bool) -> None:
        """Green dot = healthy; red dot = save failed OR hotkey untrusted."""
        self._save_ok = ok
        self._refresh_dot()

    def _refresh_dot(self) -> None:
        tips = []
        if not self._save_ok:
            tips.append(
                "Last save FAILED — notes may only exist on screen. "
                "Check disk space/permissions and retry."
            )
        if self._hotkey_ok is False:
            tips.append(
                "Global hotkey INACTIVE — enable Accessibility (+ Input "
                "Monitoring) for MeetingHUD in System Settings, then relaunch."
            )
        alert = bool(tips)
        self.dot.setProperty("alert", "true" if alert else "false")
        # Dynamic property change needs a polish cycle to re-apply QSS.
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.dot.setToolTip(" ".join(tips))

    def _confirm(self, title: str, body: str, confirm_text: str, cancel_text: str) -> bool:
        dlg = ConfirmDialog(self, title, body, confirm_text, cancel_text)
        dlg.move(self.frameGeometry().center() - dlg.rect().center())
        return dlg.exec() == QDialog.DialogCode.Accepted

    @safe_slot
    def add_note(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            return
        if len(raw) > SOFT_MAX_NOTE_CHARS and not self._confirm(
            f"Large note ({len(raw)} chars)?",
            f"This is over the {SOFT_MAX_NOTE_CHARS}-char soft limit.\n"
            "It may be an accidental paste.",
            "Save Anyway",
            "Cancel",
        ):
            return  # keep the text in the input; nothing saved, nothing lost
        now = datetime.now().astimezone()
        try:
            append_jsonl(
                {"session_id": self.session_id, "timestamp": now.isoformat(), "raw": raw}
            )
        except OSError as exc:
            print(f"[hud] save failed: {exc}", file=sys.stderr)
            self._set_save_state(False)
            return  # keep text in the input so it can be retried
        self._set_save_state(True)
        self.feed.append(render_note_html(now, raw))
        # Autoscroll to latest note.
        scrollbar = self.feed.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())
        self.note_count += 1
        self.input.clear()  # clear only the input line; feed stays visible

    @safe_slot
    def confirm_end_session(self, _checked: bool = False) -> None:
        if self.note_count == 0:
            self.end_session()
            return
        if not self._confirm(
            f"End session with {self.note_count} note(s)?",
            "Notes are already saved.\nThe feed will be cleared.",
            "End Session",
            "Keep Writing",
        ):
            return
        self.end_session()

    @safe_slot
    def end_session(self) -> None:
        now = datetime.now().astimezone()
        try:
            append_jsonl(
                {
                    "session_id": self.session_id,
                    "type": "session_end",
                    "timestamp": now.isoformat(),
                    "note_count": self.note_count,
                }
            )
        except OSError as exc:
            print(f"[hud] session seal failed: {exc}", file=sys.stderr)
            self._set_save_state(False)
            return  # do NOT wipe the feed; nothing is safely stored
        self._set_save_state(True)
        self.new_session()
        self.flash_border()

    @safe_slot
    def flash_border(self) -> None:
        # Unmistakable reset confirmation: red border + darker fill, ~0.5s.
        self._flash = True
        self.update()
        QTimer.singleShot(500, self._restore_border)

    @safe_slot
    def _restore_border(self) -> None:
        self._flash = False
        self.update()

    # -- Global hotkey (pynput, background thread) -------------------------
    def _start_global_hotkeys(self) -> None:
        try:
            from pynput import keyboard
        except Exception as exc:  # pynput missing or unsupported platform
            print(f"[hud] global hotkeys disabled: {exc}", file=sys.stderr)
            return

        bridge = self._bridge

        def on_toggle() -> None:
            _append_log("[hud] hotkey fired")
            bridge.toggle_requested.emit()

        hotkeys = {
            "<ctrl>+<shift>+<space>": on_toggle,
            "<cmd>+<shift>+<space>": on_toggle,
        }
        try:
            listener = keyboard.GlobalHotKeys(hotkeys)
        except Exception:
            # Fall back to ctrl-only (e.g. platforms where <cmd> won't parse).
            listener = keyboard.GlobalHotKeys({"<ctrl>+<shift>+<space>": on_toggle})
        self._hotkey_listener = listener

        def run() -> None:
            try:
                listener.start()
                listener.join()
            except Exception as exc:
                print(f"[hud] hotkey listener exited: {exc}", file=sys.stderr)

        self._hotkey_thread = threading.Thread(target=run, daemon=True)
        self._hotkey_thread.start()
        self._check_hotkey_trust()
        # Re-check the grant every 30s until present (user may grant mid-run,
        # though macOS usually requires a relaunch for taps to start working).
        timer = QTimer(self)
        timer.setInterval(30000)
        timer.timeout.connect(self._check_hotkey_trust)
        timer.start()
        self._trust_timer = timer

    @safe_slot
    def _check_hotkey_trust(self) -> None:
        trusted = macos_accessibility_trusted()
        if trusted is None:
            return
        self._hotkey_ok = trusted
        if not trusted:
            print(
                "[hud] WARNING: not Accessibility-trusted; the global hotkey "
                "cannot fire. Enable Accessibility (+ Input Monitoring) for "
                "MeetingHUD in System Settings, then relaunch.",
                file=sys.stderr,
            )
        elif self._trust_timer is not None:
            self._trust_timer.stop()
            self._trust_timer = None
        self._refresh_dot()

    @safe_slot
    def toggle_visibility(self, _checked: bool = False) -> None:
        if self.isVisible():
            self.hide()
            _append_log("[hud] toggle -> hidden")
        else:
            self._force_show()
            screen = self.screen()
            name = screen.name() if screen is not None else "?"
            _append_log(f"[hud] toggle -> shown on {name} at {self.pos().x()},{self.pos().y()}")

    @safe_slot
    def _force_show(self) -> None:
        """Show + focus, used by hotkey toggle, 2nd-instance nudges, launch."""
        self._move_to_active_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def _move_to_active_screen(self) -> bool:
        """Move the HUD to the screen holding the cursor (the active one).

        Multi-monitor fullscreen users swipe Spaces per display; a stationary
        window otherwise sits on the display it was last placed on. The
        cursor is the best proxy for "the screen I'm looking at".
        Preserves the window's relative position; returns True if it moved.
        """
        try:
            pos = QCursor.pos()
            target = QApplication.screenAt(pos) or QApplication.primaryScreen()
            if target is None:
                return False
            current = self.screen()
            if current is None:
                # Hidden widgets report no screen; fall back to geometry.
                current = QApplication.screenAt(self.frameGeometry().center())
            if current is not None and current.name() == target.name():
                return False
            tgeo = target.availableGeometry()
            if current is not None:
                rel = self.pos() - current.availableGeometry().topLeft()
            else:
                rel = QPoint(100, 100)
            new = tgeo.topLeft() + rel
            # Clamp fully inside the target screen.
            new.setX(min(max(new.x(), tgeo.left()), tgeo.right() - self.width()))
            new.setY(min(max(new.y(), tgeo.top()), tgeo.bottom() - self.height()))
            self.move(new)
            return True
        except Exception:
            log_exception("ScratchpadHUD._move_to_active_screen")
            return False

    # -- Cleanup ------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        try:
            if self._trust_timer is not None:
                self._trust_timer.stop()
            listener = getattr(self, "_hotkey_listener", None)
            if listener is not None:
                listener.stop()
        finally:
            super().closeEvent(event)


def _apply_macos_space_behavior(window: QWidget) -> bool:
    """Keep the HUD visible on every Space, including fullscreen apps.

    Qt's WindowStaysOnTopHint stops at Space boundaries: a fullscreen app
    lives in its own Space where the HUD isn't present — and toggling it
    there shows it on the *old* Space, which looks like a dead hotkey.
    Joining all Spaces as a fullscreen-auxiliary panel fixes both symptoms.
    Returns True when the behavior was applied.
    """
    if sys.platform != "darwin":
        return False
    try:
        import objc
        from AppKit import (
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
        )
        from ctypes import c_void_p
    except Exception as exc:
        print(f"[hud] spaces fix unavailable: {exc}", file=sys.stderr)
        return False
    try:
        window.winId()  # ensure the native NSView exists
        nsview = objc.objc_object(c_void_p=int(window.winId()))
        nswindow = nsview.window()
        if nswindow is None:
            return False
        nswindow.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        return True
    except Exception as exc:
        print(f"[hud] spaces fix failed: {exc}", file=sys.stderr)
        return False


def _install_crash_handlers() -> None:
    faulthandler.enable()

    def excepthook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[hud] fatal:\n{text}", file=sys.stderr)
        try:
            ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ERROR_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().astimezone().isoformat()} [hud] fatal:\n{text}\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook


def main() -> int:
    _install_crash_handlers()
    guard = SingleInstance()
    if not guard.acquire():
        print("[hud] another instance is running; brought it to front.", file=sys.stderr)
        return 0
    app = QApplication(sys.argv)
    # Fusion honors QSS backgrounds on all widgets; the native macOS style
    # ignores them on complex widgets (white QTextEdit viewport, etc.).
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(True)
    hud = ScratchpadHUD()
    guard.on_activate = hud._bridge.activate_requested.emit
    hud._force_show()  # lands on the active screen, then stays visible
    _apply_macos_space_behavior(hud)  # follow fullscreen apps across Spaces
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

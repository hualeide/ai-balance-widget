"""苹果风玻璃拟态：HTML/CSS 玻璃层 + Windows Acrylic。"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QPoint, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from blurwin import clear_frosted
from brandicons import BRAND, ICON_DIR
from fetchers import fetch_balance, fmt_amount

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "widget.html")
W, H = 280, 220
MIN_W, MIN_H = 260, 120
RADIUS = 32
HEAD_H = 80
ROW_H = 50


class FetchAllThread(QThread):
    done = Signal(dict)

    def run(self):
        from main import enabled_ids, load_conf

        conf = load_conf()
        ids = enabled_ids(conf)
        out: dict = {}

        def one(pid: str):
            try:
                return pid, fetch_balance(pid, conf)
            except Exception as e:
                return pid, {"ok": False, "error": str(e)[:40]}

        if not ids:
            self.done.emit(out)
            return
        with ThreadPoolExecutor(max_workers=min(4, len(ids))) as pool:
            for fut in as_completed([pool.submit(one, pid) for pid in ids]):
                pid, snap = fut.result()
                out[pid] = snap
        self.done.emit(out)


def _svg(pid: str) -> str:
    name = (BRAND.get(pid) or (None, ""))[0]
    if not name:
        return ""
    path = os.path.join(ICON_DIR, name)
    if not os.path.isfile(path):
        return ""
    raw = open(path, encoding="utf-8").read().replace("<path ", '<path fill="#ffffff" ')
    return raw.replace("<svg ", '<svg width="18" height="18" ')


class Bridge(QObject):
    def __init__(self, win: "GlassWindow"):
        super().__init__(win)
        self.win = win

    @Slot()
    def hideWin(self):
        self.win.hide()

    @Slot()
    def openSettings(self):
        self.win.open_settings()

    @Slot()
    def refresh(self):
        self.win.refresh(True)

    @Slot()
    def menu(self):
        self.win._menu(QPoint(self.win.width() // 2, 20))

    @Slot(int, int)
    def dragBy(self, dx: int, dy: int):
        self.win.move(self.win.x() + dx, self.win.y() + dy)

    @Slot(int, int, int)
    def resizeBy(self, edges: int, dx: int, dy: int):
        g = self.win.geometry()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        if edges & 1:
            x, w = x + dx, w - dx
        if edges & 2:
            w = w + dx
        if edges & 4:
            y, h = y + dy, h - dy
        if edges & 8:
            h = h + dy
        if w < MIN_W:
            if edges & 1:
                x = g.x() + g.width() - MIN_W
            w = MIN_W
        if h < MIN_H:
            if edges & 4:
                y = g.y() + g.height() - MIN_H
            h = MIN_H
        self.win.setGeometry(x, y, w, h)

    @Slot(int, int)
    def fitSize(self, w: int, h: int):
        self.win._fit(w, h)

    @Slot()
    def saveGeom(self):
        from main import save_conf

        save_conf({"glass_x": self.win.x(), "glass_y": self.win.y(), "glass_w": self.win.width(), "glass_h": self.win.height()})


class GlassPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        pass


class GlassWindow(QWidget):
    def __init__(self, on_style_restart=None):
        super().__init__()
        self._style = "glass"
        self._on_style_restart = on_style_restart
        self._settings = None
        self._thread = None
        self._busy = False
        self._snaps: dict = {}
        self.cards = {}

        self.setWindowTitle("AI Balance")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("background: transparent;")
        self.setMinimumSize(MIN_W, MIN_H)

        from main import enabled_ids, load_conf

        conf = load_conf()
        n = max(1, len(enabled_ids(conf)))
        self.resize(W, HEAD_H + ROW_H * n)
        if "glass_x" in conf and "glass_y" in conf:
            self.move(int(conf["glass_x"]), int(conf["glass_y"]))
        else:
            g = QApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 28, g.top() + 72)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground)
        self.view.setAttribute(Qt.WA_NoSystemBackground)
        self.view.setStyleSheet("background: transparent;")
        page = GlassPage(self.view)
        page.setBackgroundColor(QColor(0x3A, 0x44, 0x58))
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        self.view.setPage(page)
        self.bridge = Bridge(self)
        ch = QWebChannel(page)
        ch.registerObject("bridge", self.bridge)
        page.setWebChannel(ch)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        html = open(WEB, encoding="utf-8").read()
        self.view.setHtml(html, QUrl.fromLocalFile(os.path.dirname(WEB) + os.sep))

        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh(False))
        self.timer.start(60000)
        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._pin_top)
        self._top_timer.start(4000)
        QTimer.singleShot(400, lambda: self.refresh(True))
        QTimer.singleShot(0, self._after_show)

    def _fit(self, w: int, h: int):
        screen = QApplication.primaryScreen().availableGeometry()
        w = max(MIN_W, min(int(w), screen.width() - 24))
        h = max(MIN_H, min(int(h), screen.height() - 24))
        if abs(w - self.width()) > 2 or abs(h - self.height()) > 2:
            self.resize(w, h)

    def _clip_round(self):
        try:
            import ctypes

            hwnd = int(self.winId())
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            dpr = float(self.devicePixelRatioF())
            w = int(round(self.width() * dpr))
            h = int(round(self.height() * dpr))
            r = int(round(RADIUS * 2 * dpr))
            hrgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
            user32.SetWindowRgn(hwnd, hrgn, True)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._clip_round()

    def _after_show(self):
        clear_frosted(int(self.winId()))
        self._clip_round()
        self._pin_top()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._after_show)

    def _pin_top(self):
        if not self.isVisible():
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            self._clip_round()
        except Exception:
            pass

    def open_settings(self):
        from main import SettingsDialog

        if self._settings is not None:
            try:
                self._settings.close()
            except Exception:
                pass
        self._settings = SettingsDialog()
        self._settings.saved.connect(self.apply_settings)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def apply_settings(self):
        from main import load_conf

        if str(load_conf().get("style") or "whale") != "glass":
            if self._on_style_restart:
                QTimer.singleShot(0, self._on_style_restart)
            return
        self.refresh(True)

    def refresh(self, manual: bool):
        if self._busy:
            return
        self._busy = True
        self._thread = FetchAllThread()
        self._thread.done.connect(self._on_fetch)
        self._thread.start()

    def _on_fetch(self, data: dict):
        from main import enabled_ids, provider_rows

        self._busy = False
        self._snaps = data or {}
        rows = []
        oks = []
        for pid, _s, name in provider_rows():
            if pid not in enabled_ids():
                continue
            snap = self._snaps.get(pid) or {}
            rows.append({
                "id": pid,
                "name": name,
                "svg": _svg(pid),
                "amount": (snap.get("error") or "失败")[:14] if not snap.get("ok") else fmt_amount(snap),
            })
            if snap.get("ok"):
                oks.append(snap)
        self._fit(W, HEAD_H + ROW_H * max(1, len(rows)))
        usd = cny = 0.0
        has_usd = has_cny = False
        for s in oks:
            try:
                n = float(s.get("amount"))
            except (TypeError, ValueError):
                continue
            if s.get("unit") == "USD":
                usd += n
                has_usd = True
            elif s.get("unit") == "CNY":
                cny += n
                has_cny = True
        if has_usd:
            total = f"${usd:.2f}"
        elif has_cny:
            total = f"¥{cny:.2f}"
        elif oks:
            total = fmt_amount(oks[0])
        else:
            total = "--"
        payload = {
            "ok": bool(oks),
            "rows": rows,
            "total": total,
        }
        import json

        js = "window.updateData && window.updateData(" + json.dumps(payload, ensure_ascii=False) + ")"
        self.view.page().runJavaScript(js)

    def _menu(self, pos: QPoint):
        from main import save_conf

        m = QMenu(self)
        m.addAction("设置", self.open_settings)
        m.addAction("刷新", lambda: self.refresh(True))
        m.addAction("小鲸鱼外观", lambda: (save_conf({"style": "whale"}), self._on_style_restart and QTimer.singleShot(0, self._on_style_restart)))
        m.addSeparator()
        m.addAction("退出", QApplication.quit)
        m.exec(self.mapToGlobal(pos))

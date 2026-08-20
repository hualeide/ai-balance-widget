"""AI 余额桌宠：透明置顶小鲸鱼。"""
from __future__ import annotations

import ctypes
import json
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QFrame,
    QPushButton,
    QScrollArea,
    QStyleFactory,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from fetchers import PRESETS, fetch_balance, fmt_amount, get_api_key

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  须在 QApplication 之前
except Exception:
    pass

WHALE = os.path.join(os.path.dirname(ROOT), "assets", "DSniang02.png")
if not os.path.isfile(WHALE):
    WHALE = os.path.join(ROOT, "assets", "DSniang02.png")

CONF_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ai-balance-widget")
CONF_PATH = os.path.join(CONF_DIR, "config.json")
STARTUP_NAME = "AI余额桌宠.bat"

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

SESSION_PROVIDERS = [
    ("cursor", "Cursor", "Cursor 额度"),
    ("chatgpt", "GPT", "ChatGPT 额度"),
    ("google", "Gemini", "Gemini 额度"),
]
DEFAULT_ENABLED = ["cursor", "chatgpt", "google", "deepseek"]


def load_conf() -> dict:
    try:
        with open(CONF_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_conf(data: dict) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    old = load_conf()
    old.update(data)
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=2)


def provider_rows(conf: dict | None = None) -> list[tuple[str, str, str]]:
    conf = conf if conf is not None else load_conf()
    rows = list(SESSION_PROVIDERS)
    for p in PRESETS:
        rows.append((p["id"], p["short"], p["label"]))
    for item in conf.get("custom") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            (
                str(item["id"]),
                str(item.get("short") or "自定义")[:6],
                str(item.get("name") or "自定义"),
            )
        )
    return rows


def enabled_ids(conf: dict | None = None) -> list[str]:
    conf = conf if conf is not None else load_conf()
    valid = [p[0] for p in provider_rows(conf)]
    ids = conf.get("enabled")
    if not isinstance(ids, list):
        ids = list(DEFAULT_ENABLED)
    out = [i for i in ids if i in valid]
    return out or valid[:1]


def startup_path() -> str:
    return os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
        STARTUP_NAME,
    )


def is_startup() -> bool:
    return os.path.isfile(startup_path())


def set_startup(on: bool) -> None:
    path = startup_path()
    if on:
        bat = os.path.join(os.path.dirname(ROOT), "启动桌宠.bat")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="gbk") as f:
            f.write(f'@echo off\r\nstart "" "{bat}"\r\n')
    elif os.path.isfile(path):
        os.remove(path)


def apply_light_dialog(dlg: QDialog) -> None:
    dlg.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#f4f6fb"))
    pal.setColor(QPalette.WindowText, QColor("#0f172a"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.Text, QColor("#0f172a"))
    pal.setColor(QPalette.Button, QColor("#e2e8f0"))
    pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
    pal.setColor(QPalette.PlaceholderText, QColor("#64748b"))
    pal.setColor(QPalette.Highlight, QColor("#2563eb"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    dlg.setPalette(pal)
    dlg.setStyleSheet(
        """
        QDialog, QWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: #f4f6fb; color: #0f172a; font-size: 14px; }
        QLabel { color: #0f172a; }
        QCheckBox { color: #0f172a; spacing: 8px; }
        QCheckBox::indicator { width: 18px; height: 18px; }
        QLineEdit, QComboBox { color: #0f172a; background: #ffffff; border: 1px solid #94a3b8; border-radius: 6px; padding: 6px 8px; }
        QPushButton { color: #0f172a; background: #e2e8f0; border: 1px solid #94a3b8; border-radius: 6px; padding: 6px 14px; }
        QPushButton:default { color: #ffffff; background: #2563eb; border: 1px solid #1d4ed8; }
        """
    )


class CustomDialog(QDialog):
    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.setWindowTitle("自定义平台")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setModal(True)
        self.setMinimumWidth(460)
        apply_light_dialog(self)
        item = item or {}
        self.item_id = str(item.get("id") or ("c_" + secrets.token_hex(4)))

        form = QFormLayout(self)
        self.name = QLineEdit(str(item.get("name") or ""))
        self.name.setPlaceholderText("例如 某云 API")
        self.short = QLineEdit(str(item.get("short") or ""))
        self.short.setPlaceholderText("底部按钮，最多 6 字")
        self.short.setMaxLength(6)
        self.url = QLineEdit(str(item.get("url") or ""))
        self.url.setPlaceholderText("https://api.example.com/v1/user")
        self.path = QLineEdit(str(item.get("json_path") or ""))
        self.path.setPlaceholderText("data.totalBalance")
        self.unit = QComboBox()
        self.unit.addItems(["CNY", "USD", "%", "次"])
        u = str(item.get("unit") or "CNY")
        i = self.unit.findText(u)
        self.unit.setCurrentIndex(i if i >= 0 else 0)
        self.key = QLineEdit(str(item.get("api_key") or ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Bearer Token / API Key")
        form.addRow("名称", self.name)
        form.addRow("简称", self.short)
        form.addRow("GET 地址", self.url)
        form.addRow("JSON 路径", self.path)
        form.addRow("单位", self.unit)
        form.addRow("API Key", self.key)
        hint = QLabel("请求会带 Authorization: Bearer。路径用点号，例如 data.balance 或 items.0.amount。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#334155;font-size:13px;")
        form.addRow(hint)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("确定")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        form.addRow(btns)

    def _ok(self):
        if not self.url.text().strip() or not self.path.text().strip():
            QMessageBox.warning(self, "自定义", "地址和 JSON 路径都要填。")
            return
        self.accept()

    def result_item(self) -> dict:
        name = self.name.text().strip() or "自定义"
        return {
            "id": self.item_id,
            "name": name,
            "short": (self.short.text().strip() or name[:4])[:6],
            "url": self.url.text().strip(),
            "json_path": self.path.text().strip(),
            "unit": self.unit.currentText(),
            "api_key": self.key.text().strip(),
        }


class SettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI余额桌宠 · 设置")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setModal(False)
        self.setMinimumWidth(480)
        self.resize(500, 640)
        apply_light_dialog(self)

        conf = load_conf()
        keys = conf.get("api_keys") if isinstance(conf.get("api_keys"), dict) else {}
        self.custom_items = [x for x in (conf.get("custom") or []) if isinstance(x, dict) and x.get("id")]
        self._enabled_set = set(enabled_ids(conf))
        self.checks = {}
        self.key_edits = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        look = QHBoxLayout()
        look.addWidget(QLabel("外观"))
        self.style_box = QComboBox()
        self.style_box.addItems(["小鲸鱼", "透明卡片"])
        self.style_box.setCurrentIndex(1 if str(conf.get("style") or "") == "glass" else 0)
        look.addWidget(self.style_box, 1)
        root.addLayout(look)
        look_hint = QLabel("小鲸鱼还是原来那只。透明卡片一次列出所有已勾选的平台。")
        look_hint.setWordWrap(True)
        look_hint.setStyleSheet("color:#334155;font-size:13px;")
        root.addWidget(look_hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        body = QVBoxLayout(inner)
        body.setSpacing(10)

        body.addWidget(QLabel("登录态（本机浏览器 / Cursor）"))
        for pid, _short, label in SESSION_PROVIDERS:
            box = QCheckBox(label)
            box.setChecked(pid in self._enabled_set)
            self.checks[pid] = box
            body.addWidget(box)
        hint = QLabel("Cursor 读本机登录；ChatGPT / Gemini 用 Edge 或 Chrome 的登录态。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#334155;font-size:13px;")
        body.addWidget(hint)

        body.addWidget(QLabel("API Key 平台"))
        show_key = QCheckBox("显示密钥")
        body.addWidget(show_key)
        for preset in PRESETS:
            pid = preset["id"]
            box = QCheckBox(preset["label"])
            box.setChecked(pid in self._enabled_set)
            self.checks[pid] = box
            body.addWidget(box)
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.Password)
            edit.setPlaceholderText(preset.get("placeholder") or "API Key")
            val = str(keys.get(pid) or "")
            if pid == "deepseek" and not val:
                val = str(conf.get("deepseek_api_key") or "")
            edit.setText(val)
            self.key_edits[pid] = edit
            body.addWidget(edit)
        show_key.toggled.connect(self._toggle_keys)

        head = QHBoxLayout()
        head.addWidget(QLabel("自定义平台"))
        head.addStretch()
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_custom)
        head.addWidget(add_btn)
        body.addLayout(head)
        self.custom_host = QVBoxLayout()
        self.custom_host.setSpacing(6)
        body.addLayout(self.custom_host)
        body.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self.boot = QCheckBox("开机启动")
        self.boot.setChecked(is_startup())
        root.addWidget(self.boot)

        btns = QHBoxLayout()
        btns.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("关闭")
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)
        self._fill_custom()

    def _toggle_keys(self, show: bool):
        mode = QLineEdit.Normal if show else QLineEdit.Password
        for edit in self.key_edits.values():
            edit.setEchoMode(mode)

    def _sync_enabled(self):
        for pid, box in list(self.checks.items()):
            try:
                if box.isChecked():
                    self._enabled_set.add(pid)
                else:
                    self._enabled_set.discard(pid)
            except RuntimeError:
                pass

    def _fill_custom(self):
        self._sync_enabled()
        while self.custom_host.count():
            item = self.custom_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, item in enumerate(self.custom_items):
            pid = str(item["id"])
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(f"{item.get('name') or '自定义'}（{item.get('short') or ''}）")
            box.setChecked(pid in self._enabled_set)
            self.checks[pid] = box
            edit = QPushButton("改")
            edit.clicked.connect(lambda _=False, idx=i: self._edit_custom(idx))
            dele = QPushButton("删")
            dele.clicked.connect(lambda _=False, idx=i: self._del_custom(idx))
            lay.addWidget(box, 1)
            lay.addWidget(edit)
            lay.addWidget(dele)
            self.custom_host.addWidget(row)

    def _add_custom(self):
        dlg = CustomDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        item = dlg.result_item()
        self.custom_items.append(item)
        self._enabled_set.add(item["id"])
        self._fill_custom()

    def _edit_custom(self, idx: int):
        if idx < 0 or idx >= len(self.custom_items):
            return
        dlg = CustomDialog(self, self.custom_items[idx])
        if dlg.exec() != QDialog.Accepted:
            return
        self.custom_items[idx] = dlg.result_item()
        self._fill_custom()

    def _del_custom(self, idx: int):
        if idx < 0 or idx >= len(self.custom_items):
            return
        pid = str(self.custom_items[idx].get("id") or "")
        self._sync_enabled()
        self.custom_items.pop(idx)
        self._enabled_set.discard(pid)
        self.checks.pop(pid, None)
        self._fill_custom()

    def _save(self):
        self._sync_enabled()
        enabled = [pid for pid, box in self.checks.items() if box.isChecked()]
        if not enabled:
            QMessageBox.warning(self, "设置", "至少勾一个平台。")
            return
        keys = {pid: edit.text().strip() for pid, edit in self.key_edits.items()}
        merged = {"api_keys": keys, "deepseek_api_key": keys.get("deepseek", "")}
        for preset in PRESETS:
            pid = preset["id"]
            if pid in enabled and not get_api_key(merged, pid):
                QMessageBox.warning(self, "设置", f"勾了 {preset['label']} 就要填 API Key。")
                return
        save_conf({
            "enabled": enabled,
            "api_keys": keys,
            "deepseek_api_key": keys.get("deepseek", ""),
            "custom": self.custom_items,
            "style": "glass" if self.style_box.currentIndex() == 1 else "whale",
        })
        set_startup(self.boot.isChecked())
        self.saved.emit()
        self.close()


class FetchThread(QThread):
    done = Signal(dict)

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def run(self):
        try:
            self.done.emit(fetch_balance(self.provider, load_conf()))
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)[:40]})


class PetWindow(QWidget):
    def __init__(self, on_style_restart=None):
        super().__init__()
        self._style = "whale"
        self._on_style_restart = on_style_restart
        self.setWindowTitle("AI余额桌宠")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.NoFocus)

        conf = load_conf()
        self.scale = float(conf.get("scale", 1.0))
        self.provider = conf.get("provider", "cursor")
        self.snap = None
        self.status = "loading"
        self.message = ""
        self._pressing = False
        self._drag = None
        self._busy = False
        self._thread = None
        self._anchor_h = "right"
        self._anchor_v = "bottom"
        self._h_off = 0
        self._v_off = 0

        self.body = QWidget(self)
        self.body.setAttribute(Qt.WA_TranslucentBackground)

        self.img = QLabel(self.body)
        self.img.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.raw = QPixmap(WHALE)

        self.text = QWidget(self.body)
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(self.text)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.label_el = QLabel()
        self.amount_el = QLabel()
        self.hint_el = QLabel()
        for el, weight in ((self.label_el, 600), (self.amount_el, 800), (self.hint_el, 400)):
            el.setAlignment(Qt.AlignCenter)
            el.setStyleSheet("background: transparent;")
            font = QFont("Microsoft YaHei UI", 10, weight)
            el.setFont(font)
            lay.addWidget(el)
        self.label_el.setStyleSheet("background:transparent; color:#536ba9;")
        self.amount_el.setStyleSheet("background:transparent; color:#536ba9;")
        self.hint_el.setStyleSheet("background:transparent; color:#9fb0d9;")

        self.size_box = QWidget(self.body)
        s_lay = QHBoxLayout(self.size_box)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(4)
        self.btn_minus = self._circle_btn("−", self._smaller)
        self.btn_plus = self._circle_btn("+", self._bigger)
        self.btn_gear = self._circle_btn("⚙", self.open_settings)
        s_lay.addWidget(self.btn_minus)
        s_lay.addWidget(self.btn_plus)
        s_lay.addWidget(self.btn_gear)
        self.size_box.hide()

        self.tabs = QWidget(self.body)
        self.tabs_lay = QHBoxLayout(self.tabs)
        self.tabs_lay.setContentsMargins(0, 0, 0, 0)
        self.tabs_lay.setSpacing(4)
        self.tab_btns = {}
        self._rebuild_tabs()
        self.tabs.hide()
        self._settings = None

        self._apply_size()
        self._place_default()
        if "x" in conf and "y" in conf:
            self.move(int(conf["x"]), int(conf["y"]))
            self._recompute_anchor()

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh(False))
        self.timer.start(60000)

        self.squash = QPropertyAnimation(self.body, b"geometry", self)
        self.squash.setDuration(220)
        self.squash.setEasingCurve(QEasingCurve.OutBack)

        self._hide_chrome = QTimer(self)
        self._hide_chrome.setSingleShot(True)
        self._hide_chrome.timeout.connect(self._really_hide_chrome)

        self._top_timer = QTimer(self)
        self._top_timer.timeout.connect(self._pin_top)
        self._top_timer.start(800)

        self.refresh(True)
        QTimer.singleShot(0, self._pin_top)

    def _circle_btn(self, text, slot) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(20, 20)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            "QPushButton{border:none;border-radius:10px;background:rgba(83,107,169,0.85);color:#fff;font-size:13px;}"
            "QPushButton:hover{background:#536ba9;}"
        )
        b.clicked.connect(slot)
        return b

    def _u(self) -> float:
        return self._base / 1026.0

    def _apply_size(self):
        self.scale = max(0.6, min(1.4, round(self.scale, 1)))
        screen = QApplication.primaryScreen().availableGeometry()
        self._base = int(max(96, min(292, min(196, min(screen.width(), screen.height()) * 0.22) * self.scale)))
        self.setFixedSize(self._base, self._base)
        self.body.setGeometry(0, 0, self._base, self._base)
        pix = self.raw.scaled(self._base, self._base, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self._anchor_h == "left":
            pix = pix.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)
        self.img.setPixmap(pix)
        self.img.setGeometry(0, 0, self._base, self._base)

        tw, th = int(self._base * 0.70), int(self._base * 0.36)
        if self._anchor_h == "left":
            cx = int(self._base * (1 - 0.44346))
        else:
            cx = int(self._base * 0.44346)
        cy = int(self._base * 0.255)
        self.text.setGeometry(cx - tw // 2, cy - th // 2, tw, th)
        self._style_text_fonts()

        self.size_box.setGeometry(self._base - 72, 4, 70, 20)
        self.tabs.adjustSize()
        tw2 = min(self.tabs.sizeHint().width(), self._base)
        self.tabs.setGeometry(max(0, (self._base - tw2) // 2), int(self._base * 0.78), tw2, 22)
        self._style_tabs()
        self._paint_text()

    def _rebuild_tabs(self):
        while self.tabs_lay.count():
            item = self.tabs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.tab_btns = {}
        on = enabled_ids()
        for pid, short, _ in provider_rows():
            if pid not in on:
                continue
            b = QPushButton(short)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(20)
            b.clicked.connect(lambda checked=False, p=pid: self.switch_provider(p))
            self.tabs_lay.addWidget(b)
            self.tab_btns[pid] = b
        if on and self.provider not in on:
            self.provider = on[0]
            self.snap = None
            save_conf({"provider": self.provider})

    def open_settings(self):
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
        if str(load_conf().get("style") or "whale") == "glass":
            if self._on_style_restart:
                QTimer.singleShot(0, self._on_style_restart)
            return
        self._rebuild_tabs()
        self._apply_size()
        self.refresh(True)

    def _style_tabs(self):
        n = max(1, len(self.tab_btns))
        pad = 4 if n > 4 else 7
        fs = 10 if n > 4 else 11
        for pid, btn in self.tab_btns.items():
            on = pid == self.provider
            bg = "#536ba9" if on else "rgba(83,107,169,0.85)"
            btn.setStyleSheet(
                f"QPushButton{{border:none;border-radius:10px;padding:0 {pad}px;background:{bg};color:#fff;font-size:{fs}px;}}"
                "QPushButton:hover{background:#536ba9;}"
            )

    def _place_default(self):
        g = QApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self._base, g.bottom() - self._base)
        self._anchor_h, self._anchor_v = "right", "bottom"

    def _paint_text(self):
        name = next((p[2] for p in provider_rows() if p[0] == self.provider), "额度")
        self.label_el.setText(name)
        if self.status == "error":
            self.amount_el.setText(fmt_amount(self.snap) if self.snap and self.snap.get("ok") else "--")
            self.hint_el.setText((self.message or "获取失败")[:14])
        elif self.snap and self.snap.get("ok"):
            self.amount_el.setText(fmt_amount(self.snap))
            self.hint_el.setText("加载中…" if self.status == "changing" else (self.snap.get("hint") or "点击刷新"))
        else:
            self.amount_el.setText("…")
            self.hint_el.setText("加载中…")
        self._style_tabs()
        self._style_text_fonts()

    def _style_text_fonts(self):
        u = self._u()
        broke = bool(self.snap and self.snap.get("broke") and self.status != "error")
        amt_color = "#c45c6a" if broke else "#536ba9"
        hint = (self.snap or {}).get("hint") or ""
        auto_line = hint.startswith("Auto")
        self.label_el.setStyleSheet(
            f"background:transparent;color:#536ba9;font-size:{max(10, int(u * 64))}px;font-weight:600;"
        )
        self.amount_el.setStyleSheet(
            f"background:transparent;color:{amt_color};font-size:{max(14, int(u * 110))}px;font-weight:800;"
        )
        self.hint_el.setStyleSheet(
            f"background:transparent;color:#536ba9;font-size:{max(13, int(u * (92 if auto_line else 72)))}px;"
            f"font-weight:{700 if auto_line else 600};"
        )

    def paintEvent(self, e):
        # alpha=1 整块可点，避免透明像素点穿到 Cursor 里
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._pin_top)

    def _pin_top(self):
        if not self.isVisible():
            return
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
        except Exception:
            pass

    def enterEvent(self, e):
        self._hide_chrome.stop()
        self.size_box.show()
        self.tabs.show()
        self._pin_top()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._pressing:
            self._hide_chrome.start(600)
        super().leaveEvent(e)

    def _really_hide_chrome(self):
        if self._pressing or self.underMouse():
            return
        self.size_box.hide()
        self.tabs.hide()

    def _smaller(self):
        self.scale = round(self.scale - 0.1, 1)
        self._apply_size()
        self._settle()
        save_conf({"scale": self.scale})

    def _bigger(self):
        self.scale = round(self.scale + 0.1, 1)
        self._apply_size()
        self._settle()
        save_conf({"scale": self.scale})

    def switch_provider(self, pid: str):
        if pid == self.provider:
            self.refresh(True)
            return
        self.provider = pid
        self.snap = None
        save_conf({"provider": pid})
        self.refresh(True)

    def refresh(self, manual: bool):
        if self._busy:
            return
        self._busy = True
        if manual or not self.snap:
            self.status = "loading"
            self._paint_text()
        self._thread = FetchThread(self.provider)
        self._thread.done.connect(lambda d: self._on_fetch(d, manual))
        self._thread.start()

    def _on_fetch(self, data: dict, manual: bool):
        self._busy = False
        if not data.get("ok"):
            self.status = "error"
            self.message = data.get("error") or "获取失败"
        else:
            self.snap = data
            self.status = "ok"
            self.message = ""
        self._apply_size()

    def _work_area(self) -> QRect:
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _press_geom(self, down: bool) -> QRect:
        w = h = self._base
        if not down:
            return QRect(0, 0, w, h)
        nw, nh = int(w * 1.05), int(h * 0.88)
        return QRect(int((w - nw) / 2), h - nh, nw, nh)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.childAt(e.position().toPoint()) in (self.btn_minus, self.btn_plus, self.btn_gear) or (
            self.tabs.geometry().contains(e.position().toPoint()) and self.tabs.isVisible()
        ):
            return
        self._pressing = True
        self._drag = {
            "start": e.globalPosition().toPoint(),
            "orig": self.pos(),
            "moved": False,
        }
        self.setCursor(Qt.ClosedHandCursor)
        self.squash.stop()
        self.squash.setStartValue(self.body.geometry())
        self.squash.setEndValue(self._press_geom(True))
        self.squash.start()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        delta = e.globalPosition().toPoint() - self._drag["start"]
        if delta.manhattanLength() >= 4:
            self._drag["moved"] = True
        self.move(self._drag["orig"] + delta)

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        moved = self._drag["moved"]
        self._drag = None
        self._pressing = False
        self.setCursor(Qt.ArrowCursor)
        self.squash.stop()
        self.squash.setStartValue(self.body.geometry())
        self.squash.setEndValue(self._press_geom(False))
        self.squash.start()
        if not moved and e.button() == Qt.LeftButton:
            self.refresh(True)
            return
        self._snap_edges()
        self._apply_size()
        save_conf({"x": self.x(), "y": self.y(), "scale": self.scale, "provider": self.provider})

    def _snap_edges(self):
        g = self._work_area()
        c = self.frameGeometry().center()
        if c.x() < g.left() + g.width() / 4:
            self._anchor_h, self._h_off = "left", 0
        elif c.x() > g.left() + g.width() * 3 / 4:
            self._anchor_h, self._h_off = "right", 0
        else:
            self._anchor_h, self._h_off = None, self.x() - g.left()
        if c.y() < g.top() + g.height() / 4:
            self._anchor_v, self._v_off = "top", 0
        elif c.y() > g.top() + g.height() * 3 / 4:
            self._anchor_v, self._v_off = "bottom", 0
        else:
            self._anchor_v, self._v_off = None, self.y() - g.top()
        self._settle()

    def _recompute_anchor(self):
        g = self._work_area()
        r = self.frameGeometry()
        if abs(r.left() - g.left()) < 8:
            self._anchor_h = "left"
        elif abs(r.right() - g.right()) < 8:
            self._anchor_h = "right"
        else:
            self._anchor_h = None
            self._h_off = r.left() - g.left()
        if abs(r.top() - g.top()) < 8:
            self._anchor_v = "top"
        elif abs(r.bottom() - g.bottom()) < 8:
            self._anchor_v = "bottom"
        else:
            self._anchor_v = None
            self._v_off = r.top() - g.top()

    def _settle(self):
        g = self._work_area()
        x, y = self.x(), self.y()
        if self._anchor_h == "left":
            x = g.left()
        elif self._anchor_h == "right":
            x = g.right() - self._base + 1
        else:
            x = g.left() + int(self._h_off or 0)
        if self._anchor_v == "top":
            y = g.top()
        elif self._anchor_v == "bottom":
            y = g.bottom() - self._base + 1
        else:
            y = g.top() + int(self._v_off or 0)
        x = max(g.left(), min(x, g.right() - self._base))
        y = max(g.top(), min(y, g.bottom() - self._base))
        self.move(x, y)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("设置", self.open_settings)
        m.addAction("刷新", lambda: self.refresh(True))
        sub = m.addMenu("切换")
        on = enabled_ids()
        for pid, short, label in provider_rows():
            if pid not in on:
                continue
            a = sub.addAction(label)
            a.setCheckable(True)
            a.setChecked(pid == self.provider)
            a.triggered.connect(lambda checked=False, p=pid: self.switch_provider(p))
        m.addAction("透明卡片", self._to_glass)
        m.addSeparator()
        m.addAction("退出", QApplication.quit)
        m.exec(self.mapToGlobal(pos))

    def _to_glass(self):
        save_conf({"style": "glass"})
        if self._on_style_restart:
            QTimer.singleShot(0, self._on_style_restart)


def make_tray(host) -> QSystemTrayIcon:
    icon = QIcon(WHALE)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("AI余额桌宠")
    menu = QMenu()
    menu.addAction("设置", host.open_settings)
    menu.addAction("刷新", lambda: host.refresh(True))
    menu.addAction("显示/隐藏", lambda: host.setVisible(not host.isVisible()))
    menu.addSeparator()
    menu.addAction("退出", QApplication.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: host.open_settings() if r == QSystemTrayIcon.Trigger else None)
    tray.show()
    return tray


class Shell:
    def __init__(self):
        self.win = None
        self.tray = None
        self.rebuild()

    def rebuild(self):
        style = str(load_conf().get("style") or "whale")
        old = self.win
        if style == "glass":
            from glass import GlassWindow

            self.win = GlassWindow(self.rebuild)
        else:
            self.win = PetWindow(self.rebuild)
        self.win.show()
        if self.tray is None:
            self.tray = make_tray(self)
        if old is not None:
            old.hide()
            old.close()
            old.deleteLater()

    def open_settings(self):
        if self.win:
            self.win.open_settings()

    def refresh(self, manual=True):
        if self.win:
            self.win.refresh(manual)

    def setVisible(self, v):
        if self.win:
            self.win.setVisible(v)

    def isVisible(self):
        return bool(self.win and self.win.isVisible())

    def _pin_top(self):
        if self.win:
            self.win._pin_top()


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AI余额桌宠")
    shell = Shell()
    app.applicationStateChanged.connect(lambda *_: shell._pin_top())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

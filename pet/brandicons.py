"""各家官方图标（simple-icons SVG）。"""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(os.path.dirname(ROOT), "assets", "icons")

_cache: dict[tuple[str, int], QPixmap] = {}

# pid -> (svg 文件名, 底色)
BRAND = {
    "cursor": ("cursor.svg", "#000000"),
    "chatgpt": ("openai.svg", "#10A37F"),
    "google": ("googlegemini.svg", "#8E75B2"),
    "deepseek": ("deepseek.svg", "#4D6BFE"),
    "openrouter": ("openrouter.svg", "#1A1A1A"),
    "moonshot": ("kimi.svg", "#000000"),
    "siliconflow": (None, "#7C3AED"),
}


def brand_color(pid: str) -> QColor:
    return QColor(BRAND.get(pid, (None, "#6366F1"))[1])


def icon_pix(pid: str, size: int = 48) -> QPixmap:
    key = (pid, size)
    if key in _cache:
        return _cache[key]
    svg_name, bg = BRAND.get(pid, (None, "#6366F1"))
    svg_path = os.path.join(ICON_DIR, svg_name) if svg_name else ""
    if svg_path and os.path.isfile(svg_path):
        pix = _from_svg(svg_path, size, bg, pid == "google")
    else:
        pix = _fallback(pid, size, bg)
    _cache[key] = pix
    return pix


def _from_svg(path: str, size: int, bg: str, gemini: bool) -> QPixmap:
    raw = open(path, encoding="utf-8").read().replace("<path ", '<path fill="#ffffff" ')
    renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")))
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    if gemini:
        g = QLinearGradient(0, 0, size, size)
        g.setColorAt(0.0, QColor("#4B8BFA"))
        g.setColorAt(0.55, QColor("#8E75B2"))
        g.setColorAt(1.0, QColor("#E879F9"))
        p.setBrush(g)
    else:
        p.setBrush(QColor(bg))
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    pad = size * 0.18
    renderer.render(p, QRectF(pad, pad, size - 2 * pad, size - 2 * pad))
    p.end()
    return out


def _fallback(pid: str, size: int, bg: str) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    p.setPen(QColor("#fff"))
    p.setBrush(Qt.NoBrush)
    letter = {"siliconflow": "硅"}.get(pid, "?")
    p.drawText(out.rect(), Qt.AlignCenter, letter)
    p.end()
    return out

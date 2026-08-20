"""生成 README 横幅预览图（1280x640，离屏渲染，不弹窗口）。

用法：
    .venv\\Scripts\\python.exe tools\\make_banner.py
输出：
    assets/banner.png
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication

W, H = 1280, 640
OUT = os.path.join(ROOT, "assets", "banner.png")
WHALE = os.path.join(ROOT, "assets", "DSniang02.png")

ACCENT = QColor("#8be9fd")
BODY = QColor("#9aa4c0")
DIM = QColor("#6b7594")


def font(size: int, bold: bool = False) -> QFont:
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def main() -> None:
    app = QApplication(sys.argv)

    pix = QPixmap(W, H)
    pix.fill(QColor("#1b1e28"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    # 背景渐变
    grad = QLinearGradient(0, 0, W, H)
    grad.setColorAt(0.0, QColor("#232736"))
    grad.setColorAt(1.0, QColor("#13151e"))
    p.fillRect(0, 0, W, H, QBrush(grad))

    # 鲸鱼背后的柔和光晕
    glow = QRadialGradient(QPointF(W * 0.80, H * 0.52), H * 0.75)
    glow.setColorAt(0.0, QColor(0, 200, 216, 50))
    glow.setColorAt(1.0, QColor(0, 200, 216, 0))
    p.fillRect(0, 0, W, H, QBrush(glow))

    # 标题
    p.setPen(QColor("#ffffff"))
    p.setFont(font(58, True))
    p.drawText(QRectF(64, 92, 640, 80), Qt.AlignLeft | Qt.AlignVCenter, "AI 余额桌宠")

    # 副标题
    p.setPen(BODY)
    p.setFont(font(24))
    p.drawText(QRectF(64, 178, 680, 40), Qt.AlignLeft | Qt.AlignVCenter, "多平台 AI 额度监控 · 透明置顶小鲸鱼")

    # 特性标签
    chips = ["拖拽吸附", "左翻转身", "按压 Q 弹", "数字滚动"]
    x = 64.0
    for c in chips:
        w = QFontMetrics(font(19)).horizontalAdvance(c) + 36
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, 236, w, 42), 21, 21)
        p.fillPath(path, QColor(38, 46, 66, 235))
        p.setPen(ACCENT)
        p.setFont(font(19))
        p.drawText(QRectF(x, 236, w, 42), Qt.AlignCenter, c)
        x += w + 16

    # 平台列表
    p.setPen(DIM)
    p.setFont(font(17))
    p.drawText(
        QRectF(64, 322, 600, 30),
        Qt.AlignLeft | Qt.AlignVCenter,
        "Cursor · ChatGPT · Gemini · DeepSeek · OpenAI · OpenRouter · 硅基流动 · Kimi · 自定义",
    )

    # 鲸鱼
    whale = QPixmap(WHALE)
    wh = int(H * 0.84)
    ww = int(wh * whale.width() / whale.height())
    p.drawPixmap(int(W - ww - 56), int((H - wh) / 2), ww, wh, whale)

    # 气泡
    bubble = QRectF(W - ww - 436, 86, 372, 96)
    bp = QPainterPath()
    bp.addRoundedRect(bubble, 18, 18)
    tail = QPainterPath()
    tail.moveTo(bubble.right() - 64, bubble.bottom() - 4)
    tail.lineTo(bubble.right() - 30, bubble.bottom() + 26)
    tail.lineTo(bubble.right() - 10, bubble.bottom() - 2)
    tail.closeSubpath()
    p.fillPath(bp, QColor(255, 255, 255, 238))
    p.fillPath(tail, QColor(255, 255, 255, 238))

    p.setPen(QColor("#1b1e28"))
    p.setFont(font(17, True))
    p.drawText(bubble.adjusted(18, 10, -18, -52), Qt.AlignLeft | Qt.AlignVCenter, "今日余额")
    p.setPen(QColor("#0d8a6a"))
    p.setFont(font(19, True))
    p.drawText(bubble.adjusted(18, 50, -18, -8), Qt.AlignLeft | Qt.AlignVCenter, "Cursor $12.34 · GPT 8% · Gemini 2%")

    # 页脚
    p.setPen(QColor("#4a5370"))
    p.setFont(font(15))
    p.drawText(QRectF(64, H - 48, 600, 28), Qt.AlignLeft | Qt.AlignVCenter, "github.com/hualeide/ai-balance-widget")

    p.end()
    ok = pix.save(OUT)
    if not ok:
        print("保存失败", OUT)
        sys.exit(1)
    print("已保存", OUT, f"{pix.width()}x{pix.height()}")


if __name__ == "__main__":
    main()

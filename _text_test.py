import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication([])

OLD = "Cursor · ChatGPT · Gemini · DeepSeek · OpenRouter · 硅基流动 · Kimi · 自定义"
NEW = "Cursor · ChatGPT · Gemini · DeepSeek · OpenAI · OpenRouter · 硅基流动 · Kimi · 自定义"


def render(text: str, path: str):
    pix = QPixmap(1280, 640)
    pix.fill(QColor("#13151e"))
    p = QPainter(pix)
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(17)
    p.setFont(f)
    p.setPen(QColor("#6b7594"))
    p.drawText(QRectF(64, 322, 600, 30), Qt.AlignLeft | Qt.AlignVCenter, text)
    p.end()
    pix.save(path)


render(OLD, "_old.png")
render(NEW, "_new.png")

import hashlib


def h(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


print("old:", h("_old.png"))
print("new:", h("_new.png"))
print("identical:", h("_old.png") == h("_new.png"))

import os
import sys
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon
from PyQt6.QtCore import Qt, QByteArray, QSize
from PyQt6.QtSvg import QSvgRenderer

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    
    return os.path.join(base_path, relative_path)

def render_svg_icon(svg_data: str, color: str, size: int = 24) -> QIcon:
 
    colored_svg_data = svg_data.replace('currentColor', color)
    byte_array = QByteArray(colored_svg_data.encode('utf-8'))
    renderer = QSvgRenderer(byte_array)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

def create_view_icon(mode='grid', size=24, color=QColor("#e0e0e0")):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    if mode == 'grid':
        s = size / 4.5
        gap = s / 2.0
        margin = (size - (2*s + gap)) / 2
        painter.drawRect(int(margin), int(margin), int(s), int(s))
        painter.drawRect(int(margin + s + gap), int(margin), int(s), int(s))
        painter.drawRect(int(margin), int(margin + s + gap), int(s), int(s))
        painter.drawRect(int(margin + s + gap), int(margin + s + gap), int(s), int(s))
    else: # list
        s = size / 5.0
        margin = s
        gap = (size - 2*margin - 3*2) / 2 
        y1 = margin
        y2 = margin + 2 + gap
        y3 = y2 + 2 + gap
        painter.drawLine(int(margin), int(y1), int(size - margin), int(y1))
        painter.drawLine(int(margin), int(y2), int(size - margin), int(y2))
        painter.drawLine(int(margin), int(y3), int(size - margin), int(y3))

    painter.end()
    return QIcon(pixmap)
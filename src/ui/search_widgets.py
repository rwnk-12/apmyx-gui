import logging
import os
import sys
import urllib.request
import weakref
import socket
import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QStyleOptionButton, QStyle, QApplication
)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QRunnable, QObject, Qt, QPointF, QEvent, QTimer, QRect
from PyQt6.QtGui import QPixmap, QBitmap, QPainter, QColor, QPen, QPainterPath

def round_pixmap(pixmap, radius):
    if pixmap.isNull():
        return pixmap
    
    mask = QBitmap(pixmap.size())
    mask.fill(Qt.GlobalColor.white)
    
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.black)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(pixmap.rect(), radius, radius)
    painter.end()

    pixmap.setMask(mask)
    return pixmap

def resource_path(relative_path):
    
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    return os.path.join(base_path, relative_path)

class LoadingSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._spokes = 13
        self._index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(75)
        self.setFixedSize(32, 32)
        self.inactive = QColor("#4a4a4a")
        self.active   = QColor("#e5e5e5")
        self.base_thickness = 2
        self.setToolTip("Processing...")
        self.destroyed.connect(lambda: (self._timer.stop() if self._timer is not None else None))

    def _tick(self):
        self._index = (self._index + 1) % self._spokes
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx = self.width() * 0.5
        cy = self.height() * 0.5
        size = min(self.width(), self.height())
        r_outer = size * 0.36
        r_inner = size * 0.18
        thickness = max(1.0, self.base_thickness * float(self.devicePixelRatioF()))
        for i in range(self._spokes):
            angle = 2.0 * math.pi * (i / self._spokes)
            color = self.active if i == self._index else self.inactive
            pen = QPen(color, thickness, Qt.PenStyle.SolidLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            x1 = cx + r_inner * math.cos(angle)
            y1 = cy + r_inner * math.sin(angle)
            x2 = cx + r_outer * math.cos(angle)
            y2 = cy + r_outer * math.sin(angle)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def start(self):
        self.show()
        self._timer.start()

    def stop(self):
        try:
            if self._timer is not None:
                self._timer.stop()
        except RuntimeError:
            pass
        self.hide()

class ImageFetcherSignals(QObject):
    image_loaded = pyqtSignal(bytes)
    error = pyqtSignal(str)

_IN_FLIGHT_FETCHERS = weakref.WeakSet()

class ImageFetcher(QRunnable):
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.signals = ImageFetcherSignals()
        self._cancel = False
        _IN_FLIGHT_FETCHERS.add(self)

    def cancel(self):
        self._cancel = True

    def auto_cancel_on(self, obj: QObject):
        try:
            obj.destroyed.connect(self.cancel)
        except Exception:
            pass
        return self

    @pyqtSlot()
    def run(self):
        try:
            if self._cancel:
                return
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            req = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                if self._cancel:
                    return
                image_data = response.read()
            if self._cancel:
                return
            self.signals.image_loaded.emit(image_data)
        except (socket.timeout, Exception) as e:
            if not self._cancel:
                try:
                    self.signals.error.emit(str(e))
                except RuntimeError:
                    pass
        finally:
            try:
                _IN_FLIGHT_FETCHERS.discard(self)
            except Exception:
                pass

class MarqueeLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self._scroll_pos = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._update_scroll)
        self._is_scrolling = False
        self._needs_scrolling = False
        self.setMinimumWidth(10)

    def setText(self, text):
        self._full_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        fm = self.fontMetrics()
        text_width = fm.horizontalAdvance(self._full_text)
        self._needs_scrolling = text_width > self.width()

        if self._is_scrolling:
            painter.drawText(-self._scroll_pos, self.height() - fm.descent(), self._full_text)
        else:
            elided_text = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, self.width())
            painter.drawText(0, self.height() - fm.descent(), elided_text)

    def start_animation(self):
        if self._needs_scrolling and not self._is_scrolling:
            self._is_scrolling = True
            self._timer.start()

    def stop_animation(self):
        if self._is_scrolling:
            self._is_scrolling = False
            self._timer.stop()
            self._scroll_pos = 0
            self.update()

    def _update_scroll(self):
        fm = self.fontMetrics()
        text_width = fm.horizontalAdvance(self._full_text)
        self._scroll_pos += 1
        if self._scroll_pos > text_width:
            self._scroll_pos = -self.width()
        self.update()

class SearchLineEdit(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._is_focused = False

        self.line_edit = QLineEdit(self)
        self.line_edit.setPlaceholderText("Search")
        self.line_edit.setStyleSheet("background: transparent; border: none; padding-left: 35px; font-weight: bold;")
        
        self.line_edit.installEventFilter(self)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.line_edit)

 
        self._loading = False
        self._spokes = 8
        self._spin_index = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(60)
        self._spin_timer.timeout.connect(self._update_spinner)

      
        self._inactive_color = QColor("#4a4a4a")
        self._active_color   = QColor("#e5e5e5")
        self._spoke_width = 2.0

    def setLoading(self, on: bool):
        if on and not self._loading:
            self._loading = True
            self._spin_index = 0
            self._spin_timer.start()
            self.update()
        elif not on and self._loading:
            self._loading = False
            self._spin_timer.stop()
            self.update()

    def start_loading(self):
        self.setLoading(True)

    def stop_loading(self):
        self.setLoading(False)

    def _update_spinner(self):
        self._spin_index = (self._spin_index + 1) % self._spokes
        self.update()

    def eventFilter(self, source, event):
        if source is self.line_edit:
            if event.type() == QEvent.Type.FocusIn:
                self._is_focused = True
                self.update()
            elif event.type() == QEvent.Type.FocusOut:
                self._is_focused = False
                self.update()
        return super().eventFilter(source, event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw border
        if self._is_focused:
            pen = QPen(QColor("#fd576b"), 1.5)
        else:
            pen = QPen(QColor("#888"), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

        icon_size = 14
        icon_rect = QRect(10, (self.height() - icon_size)//2, icon_size, icon_size)
        
        if self._loading:
            # Draw segmented spinner
            cx = icon_rect.center().x()
            cy = icon_rect.center().y()
            radius_outer = icon_size * 0.48
            radius_inner = icon_size * 0.20
            spoke_width = max(1.0, self._spoke_width * float(self.devicePixelRatioF()))

            for i in range(self._spokes):
                angle = 2.0 * math.pi * (i / self._spokes)
                color = self._active_color if i == self._spin_index else self._inactive_color
                pen = QPen(color, spoke_width, Qt.PenStyle.SolidLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)

                x1 = cx + radius_inner * math.cos(angle)
                y1 = cy + radius_inner * math.sin(angle)
                x2 = cx + radius_outer * math.cos(angle)
                y2 = cy + radius_outer * math.sin(angle)
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        else:
            # Draw the magnifier icon
            icon_pen = QPen(QColor("#fd576b"), 2)
            icon_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(icon_pen)
            painter.drawEllipse(icon_rect)
            handle_start = QPointF(icon_rect.right() - 2, icon_rect.bottom() - 2)
            handle_end   = QPointF(icon_rect.right() + 4, icon_rect.bottom() + 4)
            painter.drawLine(handle_start, handle_end)

    def text(self):
        return self.line_edit.text()

    def setPlaceholderText(self, text):
        self.line_edit.setPlaceholderText(text)

    @property
    def returnPressed(self):
        return self.line_edit.returnPressed

class ClickableLabel(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, text, url, parent=None, tooltip=None):
        super().__init__(text, parent)
        self.url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #888; font-size: 8pt; padding: 2px 4px;")
        if tooltip is not None:
            self.setToolTip(tooltip)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        self.clicked.emit(self.url)
        super().mousePressEvent(event)

class CustomCheckBox(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QCheckBox {
                spacing: 5px;
                color: #fff;
            }
            QCheckBox::indicator {
                width: 10px;
                height: 10px;
                border: 2px solid #666;
                border-radius: 5px;
                background-color: #8A1429;
            }
            QCheckBox::indicator:hover {
                border-color: #888;
            }
            QCheckBox::indicator:checked {
                background-color: #8A1429;
                border-color: #8A1429;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #a8243e;
                border-color: #a8243e;
            }
        """)

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            option = QStyleOptionButton()
            self.initStyleOption(option)
            indicator_rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
            
            pen_width = max(2.0, indicator_rect.height() * 0.15)
            pen = QPen(Qt.GlobalColor.white, pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            padding = indicator_rect.width() * 0.25
            
            start_point_x = indicator_rect.left() + padding
            start_point_y = indicator_rect.top() + indicator_rect.height() * 0.5
            
            mid_point_x = indicator_rect.left() + indicator_rect.width() * 0.4
            mid_point_y = indicator_rect.top() + indicator_rect.height() - padding
            
            end_point_x = indicator_rect.right() - padding
            end_point_y = indicator_rect.top() + padding * 0.8

            path = QPainterPath()
            path.moveTo(start_point_x, start_point_y)
            path.lineTo(mid_point_x, mid_point_y)
            path.lineTo(end_point_x, end_point_y)
            
            painter.drawPath(path)
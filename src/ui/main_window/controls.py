import os
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QComboBox, QButtonGroup
from PyQt6.QtCore import pyqtSignal, QRect, QPropertyAnimation, QEasingCurve, QTimer, Qt, pyqtProperty, QPointF, QRectF, QSize, QEvent
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont, QLinearGradient, QPen, QFontMetrics, QTransform, QPalette

from ..search_cards import resource_path, render_svg_tinted

class _Thumb(QWidget):
    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            r = self.rect()
            rad = r.height() / 2.0
            path = QPainterPath()
            path.addRoundedRect(QRectF(r), rad, rad)
            p.drawPath(path)
        finally:
            p.end()

class SegmentedQualitySelector(QWidget):
    selectionChanged = pyqtSignal(str)

    def __init__(self, labels=("Atmos", "Lossless", "AAC"), accent="#B03400", parent=None):
        super().__init__(parent)
        self.accent = accent
        self._min_h = 30
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._min_h)

        self.bg = QFrame(self)
        self.bg.setObjectName("SegCapsule")
        self.bg.setFrameShape(QFrame.Shape.NoFrame)
        self.bg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.bg.setStyleSheet("""
            QFrame#SegCapsule {
                background-color: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 1000px;
            }
        """)
        self.bg.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.lay = QHBoxLayout(self.bg)
        self.lay.setContentsMargins(2, 2, 2, 2)
        self.lay.setSpacing(0)

        self.thumb = _Thumb(QColor(self.accent), self.bg)
        self.thumb.lower()
        self.thumb.hide()

        self.buttons = []
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        font = QFont()
        font.setPointSize(10)
        for i, lbl in enumerate(labels):
            b = QPushButton(lbl, self.bg)
            b.setCheckable(True)
            b.setFlat(True)
            b.setAutoDefault(False)
            b.setDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(font)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setStyleSheet("""
                QPushButton,
                QPushButton:checked,
                QPushButton:hover,
                QPushButton:pressed,
                QPushButton:focus {
                    background: transparent;
                    border: none;
                }
                QPushButton {
                    color: #e0e0e0;
                    padding: 3px 10px;
                    min-height: 24px;
                }
                QPushButton:checked { color: white; }
                QPushButton:hover:!checked { color: #ffffff; }
            """)
            b.clicked.connect(lambda _, btn=b: self._on_clicked(btn))
            self.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self.buttons.append(b)
            self.button_group.addButton(b, i)

        if self.buttons:
            self.buttons[0].setChecked(True)

        self._anim = None

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._init_layout_and_thumb)

    def _init_layout_and_thumb(self):
        self._update_capsule_size()
        if (btn := self.currentButton()):
            self._move_thumb_to(btn, animate=False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_capsule_size()
        if (btn := self.currentButton()):
            self._move_thumb_to(btn, animate=False)

    def _update_capsule_size(self):
        m = self.lay.contentsMargins()
        total_w = m.left() + m.right()
        max_h = 0
        for b in self.buttons:
            sz = b.sizeHint()
            total_w += sz.width()
            max_h = max(max_h, sz.height())
        total_w += self.lay.spacing() * max(0, len(self.buttons) - 1)
        total_h = max(self._min_h, max_h + m.top() + m.bottom())
        self.setFixedSize(total_w, total_h)
        self.bg.setGeometry(0, 0, self.width(), self.height())

        rad_capsule = total_h // 2
        self.bg.setStyleSheet(f"""
            QFrame#SegCapsule {{
                background-color: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: {rad_capsule}px;
            }}
        """)

    def currentLabel(self) -> str:
        btn = self.currentButton()
        return btn.text() if btn else ""

    def currentButton(self) -> QPushButton | None:
        checked_button = self.button_group.checkedButton()
        return checked_button if isinstance(checked_button, QPushButton) else None

    def _on_clicked(self, btn: QPushButton):
        self._move_thumb_to(btn, animate=True)
        self.selectionChanged.emit(btn.text())

    def _move_thumb_to(self, btn: QPushButton, animate=True):
        r: QRect = btn.geometry()
        target = QRect(r.x() + 2, r.y() + 2, max(1, r.width() - 4), max(1, r.height() - 4))

        if not self.thumb.isVisible():
            self.thumb.setGeometry(target)
            self.thumb.show()
            return

        if animate:
            anim = QPropertyAnimation(self.thumb, b"geometry", self)
            anim.setDuration(120)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self.thumb.geometry())
            anim.setEndValue(target)
            anim.start()
            self._anim = anim
        else:
            self.thumb.setGeometry(target)

    def currentText(self) -> str:
        return self.currentLabel()

    def currentIndex(self) -> int:
        return self.button_group.checkedId()

    def setCurrentIndex(self, i: int):
        if 0 <= i < len(self.buttons):
            btn = self.buttons[i]
            if not btn.isChecked():
                btn.setChecked(True)
                self.selectionChanged.emit(btn.text())
                if self.isVisible() and self.width() > 1:
                    self._move_thumb_to(btn, animate=False)

    def setCurrentText(self, text: str):
        for i, b in enumerate(self.buttons):
            if b.text() == text:
                self.setCurrentIndex(i)
                break

class AACQualitySelector(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(['aac-lc', 'aac-binaural', 'aac-downmix'])
        self.setToolTip("Select AAC audio type")
        self.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 15px;
                padding: 4px 12px;
                font-size: 9pt;
                font-weight: bold;
                min-height: 20px;
            }
            QComboBox::drop-down {
                border: none;
                width: 0px;
            }
            QComboBox::down-arrow {
                image: none;
            }
        """)

class QueueToggleBar(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background-color: transparent; border-left: none;")
        self.setAutoFillBackground(False)
        self._is_open = False

        self._icon_size = 24
        self._icon_top  = 20
        self._text_top  = 65
        self._pen_width = 3.0
        self._openness  = 0.26

    def set_open(self, is_open):
        if self._is_open != is_open:
            self._is_open = is_open
            self.update()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def changeEvent(self, e):
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.update()
        super().changeEvent(e)

    def _separator_color(self):
        pal = self.window().palette()
        c = pal.color(QPalette.ColorRole.WindowText)
        return QColor(c.red(), c.green(), c.blue(), 60)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)  
        
        win_color = self.window().palette().color(QPalette.ColorRole.Window)
        p.fillRect(self.rect(), win_color)

    
        sep = self._separator_color()
        p.setPen(QPen(sep, 1))
   
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

       
        pen = QPen(QColor("#e0e0e0"), self._pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        size = self._icon_size
        x = (self.width() - size) // 2
        y = self._icon_top
        w = h = size
        A = QPointF(x + w * 0.35, y + h * (0.5 - self._openness))
        B = QPointF(x + w * 0.65, y + h * 0.50)
        C = QPointF(x + w * 0.35, y + h * (0.5 + self._openness))
        if not self._is_open:
            cx = x + w * 0.5
            A.setX(2 * cx - A.x()); B.setX(2 * cx - B.x()); C.setX(2 * cx - C.x())
        path = QPainterPath(); path.moveTo(A); path.lineTo(B); path.lineTo(C)
        p.drawPath(path)  

        
        p.save()
        font = self.font(); font.setPointSize(11); font.setBold(True)
        p.setFont(font); p.setPen(QColor("#ffffff"))
        text = "Download Queue"
        fm = QFontMetrics(font); tw = fm.horizontalAdvance(text)
        tx = self.width() / 2; ty = self._text_top + tw / 2
        p.translate(tx, ty); p.rotate(90)
        rect = QRectF(-tw / 2, -fm.height() / 2, tw, fm.height())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()
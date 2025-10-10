from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QFrame, QGraphicsBlurEffect,
    QGraphicsDropShadowEffect, QToolButton
)
from PyQt6.QtCore import (pyqtSignal, pyqtSlot, QThreadPool, Qt, QTimer, QPropertyAnimation, QEasingCurve, 
                          QRect, QRectF, pyqtProperty)
from PyQt6.QtGui import QPixmap, QBitmap, QPainter, QColor, QFont, QPainterPath
import logging
from ..search_widgets import ImageFetcher, ClickableLabel, CustomCheckBox
from ..search_cards import SettingsButton

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

class SegmentedTabs(QWidget):
    segmentChanged = pyqtSignal(int)

    def __init__(self, labels, accent="#fd576b", parent=None):
        super().__init__(parent)
        self.accent = accent
        self._min_h = 28
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._min_h)

        self.bg = QFrame(self)
        self.bg.setObjectName("SegCapsule")
        self.bg.setStyleSheet("background: transparent; border: none;")
        self.bg.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.lay = QHBoxLayout(self.bg)
        self.lay.setContentsMargins(2, 2, 2, 2)
        self.lay.setSpacing(0)

        self.thumb = _Thumb(QColor(self.accent), self.bg)
        self.thumb.lower()
        self.thumb.hide()

        self.buttons = []
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.Bold)
        for i, lbl in enumerate(labels):
            b = QPushButton(lbl, self.bg)
            b.setCheckable(True)
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(font)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    color: #a0a0a0;
                    padding: 1px 14px;
                    min-height: 24px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    color: #ffffff;
                }
                QPushButton:checked {
                    color: #ffffff;
                }
            """)
            b.clicked.connect(lambda _, idx=i: self._on_clicked(idx))
            self.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self.buttons.append(b)

        if self.buttons:
            self.buttons[0].setChecked(True)

        self._anim = None
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
        
        self.bg.setFixedSize(total_w, total_h)

    def currentButton(self) -> QPushButton | None:
        for b in self.buttons:
            if b.isChecked(): return b
        return None

    def _on_clicked(self, index):
        if 0 <= index < len(self.buttons):
            btn = self.buttons[index]
            for b in self.buttons:
                if b is not btn: b.setChecked(False)
            btn.setChecked(True)
            self._move_thumb_to(btn, animate=True)
            self.segmentChanged.emit(index)

    def set_current_index(self, index):
        if 0 <= index < len(self.buttons) and not self.buttons[index].isChecked():
            self._on_clicked(index)

    def _move_thumb_to(self, btn: QPushButton, animate=True):
        r: QRect = btn.geometry()
        target = QRect(r.x(), r.y(), r.width(), r.height())

        if not self.thumb.isVisible():
            self.thumb.setGeometry(target)
            self.thumb.show()
            return

        if animate:
            anim = QPropertyAnimation(self.thumb, b"geometry", self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self.thumb.geometry())
            anim.setEndValue(target)
            anim.start()
            self._anim = anim
        else:
            self.thumb.setGeometry(target)


class ArtistHeroWidget(QWidget):
    back_requested = pyqtSignal()
    download_all_requested = pyqtSignal()
    menu_requested = pyqtSignal()

    def __init__(self, artist_data, parent=None):
        super().__init__(parent)
        self.artist_data = artist_data
        self.artist_pixmap = None
        self.background_pixmap = None
        self.thread_pool = QThreadPool.globalInstance()
        
        self.expanded_height = 220
        self.setFixedHeight(self.expanded_height)
        self._heroH = self.expanded_height
        self.is_collapsed = False

        self._rescale_timer = QTimer(self)
        self._rescale_timer.setSingleShot(True)
        self._rescale_timer.setInterval(35)
        self._rescale_timer.timeout.connect(self._apply_scaled_background)
        
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Widget structure
        self.background_label = QLabel(self)
        self.background_label.setScaledContents(False)
        self.overlay = QWidget(self)
        self.content_container = QWidget(self)
        self.content_container.setStyleSheet("background: transparent;")
        
        # Layouts
        main_layout = QHBoxLayout(self.content_container)
        main_layout.setContentsMargins(30, 40, 30, 20)
        main_layout.setSpacing(30)

        self.back_label = ClickableLabel("← Back", "")
        self.back_label.setParent(self)
        self.back_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_label.setStyleSheet("""
            color: #F2F2F2;
            font-weight: 600;
            font-size: 11pt;
            background: rgba(12,12,12,160);
            border-radius: 12px;
            padding: 4px 10px;
        """)
        self.back_label.adjustSize()
        shadow = QGraphicsDropShadowEffect(self.back_label)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.back_label.setGraphicsEffect(shadow)
        self.back_label.clicked.connect(lambda: self.back_requested.emit())

        self.menu_btn = SettingsButton(self)
        self.menu_btn.setFixedSize(36, 36)
        self.menu_btn.setToolTip("Menu")
        self.menu_btn.clicked.connect(self.menu_requested.emit)

        self.top_left_controls = QWidget(self)
        top_left_layout = QHBoxLayout(self.top_left_controls)
        top_left_layout.setContentsMargins(0,0,0,0)
        top_left_layout.setSpacing(6)
        top_left_layout.addWidget(self.menu_btn)
        top_left_layout.addWidget(self.back_label)
        self.top_left_controls.setStyleSheet("background: transparent;")
        self.top_left_controls.adjustSize()

        artwork_container = QWidget()
        artwork_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        artwork_container.setFixedSize(180, 180)
        artwork_layout = QVBoxLayout(artwork_container)
        artwork_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        
        self.artwork_label = QLabel()
        self.artwork_label.setGeometry(0, 0, 180, 180)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setStyleSheet("""
            border-radius: 80px; 
            background-color: rgba(0, 0, 0, 0.3);
            border: 3px solid rgba(255, 255, 255, 0.1);
        """)
        artwork_layout.addWidget(self.artwork_label)
        main_layout.addWidget(artwork_container)

        info_container = QWidget()
        info_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        info_layout = QVBoxLayout(info_container)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        
        self.name_label = QLabel(self.artist_data.get('name', ''))
        self.name_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white; background: transparent; margin: 0;")
        self.name_label.setWordWrap(True)
        info_layout.addWidget(self.name_label)

        self.download_all_btn = QPushButton("Download Discography")
        self.download_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_all_btn.setFixedHeight(28)
        self.download_all_btn.setStyleSheet(
            "font-weight: bold; padding: 4px 12px; "
            "background-color: #B03400; border: none; border-radius: 14px;"
        )
        self.download_all_btn.clicked.connect(lambda: self.download_all_requested.emit())
        info_layout.addWidget(self.download_all_btn, 0, Qt.AlignmentFlag.AlignLeft)
        
        self.include_mv_checkbox = CustomCheckBox("Including Music Videos")
        self.include_mv_checkbox.setStyleSheet("color: #ccc; font-weight: normal; font-size: 9pt; background: transparent;")
        info_layout.addWidget(self.include_mv_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        
        main_layout.addWidget(info_container, 1)
        main_layout.setAlignment(info_container, Qt.AlignmentFlag.AlignVCenter)
        main_layout.setAlignment(artwork_container, Qt.AlignmentFlag.AlignVCenter)
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._fetch_image()

    @pyqtProperty(int)
    def heroHeight(self):
        return self._heroH

    @heroHeight.setter
    def heroHeight(self, v):
        self._heroH = int(v)
        self.setFixedHeight(self._heroH)

    def apply_collapsed_endpoint(self, collapsed: bool):
        self.is_collapsed = collapsed
        if collapsed:
            self.background_label.setGraphicsEffect(None)
        self._update_gradient()

    def _update_gradient(self):
        if self.is_collapsed:
            self.overlay.setStyleSheet("background: rgba(31,31,31,200);")
        else:
            self.overlay.setStyleSheet("""
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0.00 rgba(10,10,10,160),
                    stop: 0.60 rgba(10,10,10,100),
                    stop: 0.82 rgba(31,31,31,120),
                    stop: 1.00 rgba(31,31,31,255)
                );
            """)

    def _apply_scaled_background(self):
        if self.background_pixmap and not self.background_pixmap.isNull():
            self.background_label.setScaledContents(False)
            scaled = self.background_pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.background_label.setPixmap(scaled)
            
            if not self.is_collapsed:
                blur_effect = QGraphicsBlurEffect()
                blur_effect.setBlurRadius(16)
                blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
                self.background_label.setGraphicsEffect(blur_effect)
            else:
                self.background_label.setGraphicsEffect(None)
        
        self.background_label.lower()
        self.overlay.stackUnder(self.content_container)
        self.content_container.raise_()
        self.top_left_controls.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        self.background_label.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.content_container.setGeometry(rect)
        
        self.top_left_controls.move(20, 15)
        
        self._update_gradient()
        self._rescale_timer.start()

    def _fetch_image(self):
        artist_url = self.artist_data.get('artworkUrl', '')
        if artist_url:
            bg_url = artist_url.replace('{w}', '800').replace('{h}', '800')
            artist_worker = ImageFetcher(bg_url).auto_cancel_on(self)
            artist_worker.signals.image_loaded.connect(self._set_artist_image)
            self.thread_pool.start(artist_worker)

    @pyqtSlot(bytes)
    def _set_artist_image(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            
            self.background_pixmap = pixmap.copy()
            
            self._rescale_timer.start()
            
            size = min(pixmap.width(), pixmap.height())
            squared_pixmap = pixmap.copy(
                (pixmap.width() - size) // 2, 
                (pixmap.height() - size) // 2, 
                size, 
                size
            )
            
            mask = QBitmap(size, size)
            mask.fill(Qt.GlobalColor.white)
            painter = QPainter(mask)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.GlobalColor.black)
            painter.drawEllipse(0, 0, size, size)
            painter.end()
            
            squared_pixmap.setMask(mask)
            
            bordered_pixmap = QPixmap(166, 166)
            bordered_pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(bordered_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(0, 0, 166, 166)
            
            painter.drawPixmap(3, 3, squared_pixmap.scaled(160, 160, 
                                                         Qt.AspectRatioMode.KeepAspectRatio, 
                                                         Qt.TransformationMode.SmoothTransformation))
            painter.end()
            
            self.artwork_label.setPixmap(bordered_pixmap)
            self._update_gradient()
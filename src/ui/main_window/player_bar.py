from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QPushButton, QSlider, QStyle
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThreadPool, Qt, QPointF, QTimer, QPoint, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap, QCursor, QPainterPath
from ..search_widgets import MarqueeLabel, ImageFetcher, round_pixmap
from ..search_cards import PlayButton

class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), event.pos().x(), self.width())
            self.setValue(value)
            self.sliderMoved.emit(value)
        super().mousePressEvent(event)

class VolumeControl(QWidget):
    volume_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_hovering = False

        self.popup = QFrame(self.window())
        self.popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.popup.setFixedSize(36, 120)
        self.popup.setStyleSheet("""
            QFrame {
                background-color: rgba(55, 55, 55, 230);
                border: 1px solid #444;
                border-radius: 18px;
            }
        """)

        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(5, 15, 5, 15)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(75)
        self.slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #333;
                width: 4px;
                border-radius: 2px;
            }
            QSlider::add-page:vertical {
                background: #fd576b;
                border-radius: 2px;
            }
            QSlider::handle:vertical {
                background: #e0e0e0;
                border: 1px solid #e0e0e0;
                height: 12px;
                width: 12px;
                margin: 0 -4px;
                border-radius: 6px;
            }
        """)
        popup_layout.addWidget(self.slider)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(300)
        self.hide_timer.timeout.connect(self._check_and_hide)

        self.slider.valueChanged.connect(self.volume_changed)
        self.slider.valueChanged.connect(self.update)
        
        self.popup.enterEvent = self.on_popup_enter
        self.popup.leaveEvent = self.on_popup_leave

    def on_popup_enter(self, event):
        self.hide_timer.stop()

    def on_popup_leave(self, event):
        self.hide_timer.start()

    def _check_and_hide(self):
        cursor_pos = QCursor.pos()
        if self.geometry().contains(self.mapFromGlobal(cursor_pos)):
            return
        if self.popup.isVisible() and self.popup.geometry().contains(cursor_pos):
            return
        self.popup.hide()

    def enterEvent(self, event):
        self._is_hovering = True
        self.update()
        self.hide_timer.stop()
        self.show_popup()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovering = False
        self.update()
        self.hide_timer.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._is_hovering:
            painter.setBrush(QColor(255, 255, 255, 25))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(self.rect())

        pen = QPen(QColor("#e0e0e0"), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        w, h = self.width(), self.height()
        speaker_rect = QRectF(w * 0.25, h * 0.3, w * 0.2, h * 0.4)
        path = QPainterPath()
        path.moveTo(speaker_rect.left(), speaker_rect.top())
        path.lineTo(speaker_rect.left(), speaker_rect.bottom())
        path.lineTo(speaker_rect.right(), speaker_rect.bottom() + h * 0.05)
        path.lineTo(speaker_rect.right() + w * 0.1, speaker_rect.bottom() + h * 0.1)
        path.lineTo(speaker_rect.right() + w * 0.1, speaker_rect.top() - h * 0.1)
        path.lineTo(speaker_rect.right(), speaker_rect.top() - h * 0.05)
        path.closeSubpath()
        painter.drawPath(path)

        if self.slider.value() > 0:
            start_point = QPointF(w * 0.6, h * 0.5)
            if self.slider.value() > 66:
                painter.drawArc(QRectF(start_point.x() - 4, start_point.y() - 8, 8, 16), -45 * 16, 90 * 16)
            if self.slider.value() > 33:
                painter.drawArc(QRectF(start_point.x() - 1, start_point.y() - 5, 2, 10), -45 * 16, 90 * 16)

    def show_popup(self):
        pos = self.mapToGlobal(self.rect().topLeft())
        popup_x = pos.x() + (self.width() - self.popup.width()) // 2
        popup_y = pos.y() - self.popup.height() - 5
        self.popup.move(popup_x, popup_y)
        self.popup.show()

class PlayerCloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Stop and close player")
        self.setStyleSheet("border: none;")
        self._is_hovering = False

    def enterEvent(self, event):
        self._is_hovering = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovering = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._is_hovering:
            painter.setBrush(QColor(255, 255, 255, 25))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(self.rect())

        pen = QPen(QColor("#e0e0e0"), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        margin = 8
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())

class PlayerBar(QFrame):
    play_toggled = pyqtSignal()
    seek_requested = pyqtSignal(int)
    volume_changed = pyqtSignal(int)
    close_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayerBar")
        self.setFixedHeight(48)
        self.setStyleSheet("#PlayerBar { background-color: #2c2c2c; border-top: 1px solid #333; }")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 5, 15, 5)
        layout.setSpacing(10)
        
        self.art_container = QFrame(self)
        self.art_container.setFixedSize(38, 38)
        self.art_container.setStyleSheet("background-color: transparent;")
        
        self.art_label = QLabel(self.art_container)
        self.art_label.setGeometry(0, 0, 38, 38)
        self.art_label.setStyleSheet("border-radius: 4px; background-color: #333;")
        
        self.preview_tag = QLabel("PREVIEW", self.art_container)
        self.preview_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_tag.setStyleSheet("""
            background-color: #fd576b;
            color: white;
            border-bottom-left-radius: 4px;
            border-bottom-right-radius: 4px;
            padding: 1px;
            font-size: 6pt;
            font-weight: bold;
        """)
        self.preview_tag.setGeometry(0, 38 - 14, 38, 14)
        self.preview_tag.raise_()
        
        layout.addWidget(self.art_container)
        
        self.play_button = PlayButton(self)
        self.play_button.setFixedSize(32, 32)
        self.play_button.clicked.connect(self.play_toggled.emit)
        layout.addWidget(self.play_button)
        
        center_widget = QWidget()
        center_widget.setStyleSheet("background: transparent;")
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)

        self.track_info_label = MarqueeLabel("No song playing")
        self.track_info_label.setStyleSheet("font-weight: bold; color: #eee; background: transparent;")
        center_layout.addWidget(self.track_info_label)
        
        slider_layout = QHBoxLayout()
        slider_layout.setSpacing(8)
        
        self.current_time_label = QLabel("0:00")
        self.current_time_label.setStyleSheet("font-size: 8pt; color: #ccc; background: transparent;")
        
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 3px;
                background: #333;
                margin: 2px 0;
                border-radius: 1.5px;
            }
            QSlider::handle:horizontal {
                background: #e0e0e0;
                border: none;
                width: 10px;
                height: 10px;
                margin: -3.5px 0;
                border-radius: 5px;
            }
            QSlider::sub-page:horizontal {
                background: #fd576b;
                border: none;
                height: 3px;
                border-radius: 1.5px;
            }
        """)
        self.slider.sliderMoved.connect(self.seek_requested)
        self.slider.setEnabled(False)

        self.total_duration_label = QLabel("0:00")
        self.total_duration_label.setStyleSheet("font-size: 8pt; color: #ccc; background: transparent;")

        slider_layout.addWidget(self.current_time_label)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.total_duration_label)
        
        center_layout.addLayout(slider_layout)
        
        layout.addWidget(center_widget, 1)
        
        self.volume_control = VolumeControl(self)
        self.volume_control.volume_changed.connect(self.volume_changed)
        layout.addWidget(self.volume_control)
        
        self.close_button = PlayerCloseButton(self)
        self.close_button.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.close_button)
        
        self.worker = None

    def set_track(self, track_data):
        title = track_data.get('name', 'Unknown')
        artist = track_data.get('artist', 'Unknown')
        self.track_info_label.setText(f"{artist} • {title}")
        self._fetch_artwork(track_data.get('artworkUrl'))
        self.update_progress(0, 0)

    def set_playback_state(self, state):
        self.play_button.setState(state)
        is_interactive = state in [PlayButton.State.Playing, PlayButton.State.Paused]
        self.close_button.setEnabled(is_interactive)

    @pyqtSlot(int, int)
    def update_progress(self, position, duration):
        if duration > 0:
            self.slider.setEnabled(True)
            self.slider.setRange(0, duration)
            self.slider.setValue(position)
            
            pos_seconds = position // 1000
            dur_seconds = duration // 1000
            
            self.current_time_label.setText(f"{pos_seconds // 60}:{pos_seconds % 60:02d}")
            self.total_duration_label.setText(f"{dur_seconds // 60}:{dur_seconds % 60:02d}")
        else:
            self.slider.setEnabled(False)
            self.slider.setValue(0)
            self.current_time_label.setText("0:00")
            self.total_duration_label.setText("0:00")

    def _fetch_artwork(self, url):
        if url:
            small_url = url.replace('{w}', '80').replace('{h}', '80')
            self.worker = ImageFetcher(small_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            QThreadPool.globalInstance().start(self.worker)
        else:
            self.art_label.clear()
            self.art_label.setStyleSheet("border-radius: 4px; background-color: #333;")

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.art_label.setPixmap(round_pixmap(scaled, 4))
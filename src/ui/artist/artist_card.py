import os
import sys
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QApplication
)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThreadPool, QSize, Qt, QPointF, QEvent, QRectF, QRect
from PyQt6.QtGui import QPixmap, QMouseEvent, QBitmap, QPainter, QColor, QPen, QFontMetrics, QIcon, QFont


from ..search_widgets import LoadingSpinner, ImageFetcher, MarqueeLabel, round_pixmap
from ..search_cards import DownloadIconButton, TracklistButton, InfoIconButton, PlayButton

class HoverMask(QLabel):
    def __init__(self, track_text, year_text, parent=None):
        super().__init__(parent)
        self.track_text = track_text
        self.year_text = year_text
        self.font = QFont()
        self.font.setFamilies(["Inter Tight", "Inter", self.font.family()])
        self.font.setWeight(QFont.Weight.Bold)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(self.font)
        
        fm = QFontMetrics(self.font)
        pad = 8
        
        painter.drawText(pad, pad + fm.ascent(), self.track_text)
        painter.drawText(pad, pad + fm.height() + fm.ascent(), self.year_text)
        painter.end()

class SelectionOverlay(QWidget):
    """A dedicated widget to draw the selection UI on top of the artwork."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        art_rect = self.rect()

        # Draw selection ring
        ring_pen = QPen(QColor("#fd576b"), 2)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(art_rect.adjusted(1, 1, -1, -1), 12, 12)

        # Draw checkmark
        check_bg_rect = QRect(art_rect.right() - 22, art_rect.y() + 6, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fd576b"))
        painter.drawEllipse(check_bg_rect)
        
        check_pen = QPen(Qt.GlobalColor.white, 2)
        check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(check_pen)
        cx, cy = check_bg_rect.center().x(), check_bg_rect.center().y()
        painter.drawLine(int(cx - 3), int(cy), int(cx - 1), int(cy + 3))
        painter.drawLine(int(cx - 1), int(cy + 3), int(cx + 4), int(cy - 2))
        painter.end()

class ArtistAlbumCard(QWidget):
    """A card widget for the artist page, mimicking SearchResultCard."""
    download_requested = pyqtSignal(object)
    tracklist_requested = pyqtSignal(object)
    info_requested = pyqtSignal(object)
    selection_changed = pyqtSignal(object, bool)
    video_preview_requested = pyqtSignal(object)

    def __init__(self, album_data: dict, parent=None):
        super().__init__(parent)
        self.album_data = album_data
        attrs = self.album_data.get('attributes', {})
        self.result_data = {
            'id': self.album_data.get('id'),
            'type': self.album_data.get('type'),
            'name': attrs.get('name'),
            'artist': attrs.get('artistName'),
            'artworkUrl': attrs.get('artwork', {}).get('url'),
            'appleMusicUrl': attrs.get('url'),
            'releaseDate': attrs.get('releaseDate'),
            'trackCount': attrs.get('trackCount'),
        }

        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None
        self._is_selected = False
        
        self.setFixedSize(190, 250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        
        self.main_container = QWidget(self)
        self.main_container.setObjectName("ArtistAlbumCardContainer")
        self.main_container.setStyleSheet("""
            #ArtistAlbumCardContainer {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
            }
            #ArtistAlbumCardContainer:hover {
                border: 1px solid #555;
            }
        """)
        
        layout = QVBoxLayout(self.main_container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(self.main_container)

        self.artwork_container = QWidget()
        self.artwork_container.setFixedSize(180, 180)
        self.artwork_container.installEventFilter(self)
        
        self.artwork_label = QLabel(self.artwork_container)
        self.artwork_label.setGeometry(0, 0, 180, 180)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setText("Loading...")
        
        track_count = attrs.get('trackCount', 0)
        track_text = f"{track_count} track" if track_count == 1 else f"{track_count} tracks"
        year = (attrs.get('releaseDate') or '')[:4]

        self.hover_mask = HoverMask(track_text, year, self.artwork_container)
        self.hover_mask.setGeometry(0, 0, 180, 180)
        self.hover_mask.setStyleSheet("background-color: rgba(0,0,0,80); border-radius: 12px;")
        self.hover_mask.hide()

        self.selection_overlay = SelectionOverlay(self.artwork_container)
        self.selection_overlay.setGeometry(0, 0, 180, 180)
        self.selection_overlay.hide()

        # --- Buttons ---
        self.download_button = DownloadIconButton(self.artwork_container)
        self.tracklist_button = TracklistButton(self.artwork_container)
        self.info_button = InfoIconButton(self.artwork_container)
        self.video_preview_button = PlayButton(self.artwork_container)
        self.video_preview_button.setFixedSize(32, 32)
        self.video_preview_button.setToolTip("Play Video Preview")
        
        self.action_spinner = LoadingSpinner(self.artwork_container)
        self.action_spinner.hide()
        self.active_button = None
        
        item_type = self.album_data.get('type')
        artwork_width = 180

        self.info_button.move(5, artwork_width - self.info_button.height() - 10)
        if item_type == 'music-videos':
            self.download_button.move(artwork_width - self.download_button.width() - self.video_preview_button.width() - 10, artwork_width - self.download_button.height() - 10)
            self.video_preview_button.move(artwork_width - self.video_preview_button.width() - 5, artwork_width - self.video_preview_button.height() - 10)
            self.tracklist_button.hide()
        else:
            self.download_button.move(artwork_width - self.download_button.width() - self.tracklist_button.width() - 10, artwork_width - self.download_button.height() - 10)
            self.tracklist_button.move(artwork_width - self.tracklist_button.width() - 5, artwork_width - self.tracklist_button.height() - 10)
            self.video_preview_button.hide()

        self.download_button.clicked.connect(self.on_download_button_clicked)
        self.tracklist_button.clicked.connect(self.on_tracklist_button_clicked)
        self.info_button.clicked.connect(self.on_info_button_clicked)
        self.video_preview_button.clicked.connect(self.on_video_preview_button_clicked)
        
        self.download_button.hide()
        self.tracklist_button.hide()
        self.info_button.hide()
        self.video_preview_button.hide()
        
        layout.addWidget(self.artwork_container)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(3, 3, 3, 0)
        text_layout.setSpacing(1)

        self.title_label = MarqueeLabel(attrs.get('name', 'Unknown Title'))
        self.title_label.setStyleSheet("font-weight: bold;")
        
        details_text = attrs.get('artistName', 'Unknown Artist')
        if item_type == 'music-videos':
            details_text += " • Music Video"
        self.details_label = MarqueeLabel(details_text)
        self.details_label.setStyleSheet("color: #aaa;")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.details_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        self.main_container.installEventFilter(self)
        self._fetch_artwork()

    def isSelected(self) -> bool:
        return self._is_selected

    def setSelected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.selection_changed.emit(self, selected)
            self.selection_overlay.setVisible(selected)

    def mousePressEvent(self, event: QMouseEvent):
        if self.artwork_container.underMouse():
            local_pos = self.artwork_container.mapFrom(self, event.pos())
            if self.download_button.isVisible() and self.download_button.geometry().contains(local_pos):
                return
            if self.tracklist_button.isVisible() and self.tracklist_button.geometry().contains(local_pos):
                return
            if self.info_button.isVisible() and self.info_button.geometry().contains(local_pos):
                return
            if self.video_preview_button.isVisible() and self.video_preview_button.geometry().contains(local_pos):
                return
        
        self.setSelected(not self.isSelected())

    def eventFilter(self, source, event):
        if source is self.main_container:
            if event.type() == QEvent.Type.Enter:
                self.title_label.start_animation()
                self.details_label.start_animation()
            elif event.type() == QEvent.Type.Leave:
                self.title_label.stop_animation()
                self.details_label.stop_animation()
        
        if source is self.artwork_container:
            if event.type() == QEvent.Type.Enter:
                self.hover_mask.show()
                self.download_button.show()
                self.info_button.show()
                if self.album_data.get('type') == 'music-videos':
                    self.video_preview_button.show()
                else:
                    self.tracklist_button.show()
            elif event.type() == QEvent.Type.Leave:
                self.hover_mask.hide()
                self.download_button.hide()
                self.tracklist_button.hide()
                self.info_button.hide()
                self.video_preview_button.hide()
        return super().eventFilter(source, event)

    def _set_active_button(self, btn: QPushButton):
        self.active_button = btn
        try:
            btn.destroyed.connect(lambda: setattr(self, "active_button", None))
        except Exception:
            pass

    def on_download_button_clicked(self):
        self._set_active_button(self.download_button)
        self.download_requested.emit(self)

    def on_tracklist_button_clicked(self):
        self._set_active_button(self.tracklist_button)
        self.tracklist_requested.emit(self)

    def on_info_button_clicked(self):
        self._set_active_button(self.info_button)
        self.info_requested.emit(self)

    def on_video_preview_button_clicked(self):
        self._set_active_button(self.video_preview_button)
        self.video_preview_requested.emit(self)

    def start_action(self):
        if self.active_button:
            self.active_button.hide()
            self.action_spinner.setGeometry(self.active_button.geometry())
            self.action_spinner.start()

    def stop_action(self):
        try:
            self.action_spinner.stop()
        except RuntimeError:
            pass

        btn = getattr(self, "active_button", None)
        if btn is not None:
            try:
                if not sip.isdeleted(btn):
                    btn.show()
            except Exception:
                pass
        self.active_button = None

    def _fetch_artwork(self):
        attrs = self.album_data.get('attributes', {})
        artwork_url = attrs.get('artwork', {}).get('url')
        if artwork_url:
            formatted_url = artwork_url.replace('{w}', '360').replace('{h}', '360')
            self.worker = ImageFetcher(formatted_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            self.worker.signals.error.connect(self._on_load_error)
            self.thread_pool.start(self.worker)
        else:
            self.artwork_label.setText("No Image")

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        scaled_pixmap = pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        final_pixmap = round_pixmap(scaled_pixmap, 12)
        self.artwork_label.setPixmap(final_pixmap)

    @pyqtSlot(str)
    def _on_load_error(self, error_str: str):
        self.artwork_label.setText("Load Error")
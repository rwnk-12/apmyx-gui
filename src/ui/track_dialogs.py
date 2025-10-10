import os
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog,
    QDialogButtonBox, QScrollArea, QFrame, QPushButton, QSizePolicy, QApplication,
    QGridLayout
)
from PyQt6.QtCore import pyqtSlot, QThreadPool, Qt, QTimer, pyqtSignal, QObject, QEvent, QRect, QSize
from PyQt6.QtGui import QPixmap, QFontMetrics, QFont, QPainter, QColor, QPaintEvent

from .search_widgets import ImageFetcher, round_pixmap
from .search_cards import PlayButton, resource_path, render_svg_tinted
from .info_dialog import _ElideOnResizeFilter, ShimmerTag
from PyQt6 import sip

def _create_track_quality_widget(text: str, is_hires: bool = False, is_atmos: bool = False) -> QWidget:

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    # 1. Lossless Icon
    icon_label = QLabel()
    icon_label.setFixedSize(24, 24)
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    icon_path = resource_path('src/assets/lossless.svg')
    if os.path.exists(icon_path):
        try:
            with open(icon_path, 'rb') as f:
                svg_bytes = f.read()
            new_icon_width = 21
            new_icon_height = int(new_icon_width * (9.0 / 14.0))
            icon_color = QColor("#ffffff")
            rendered_pixmap = render_svg_tinted(svg_bytes, QSize(new_icon_width, new_icon_height), icon_color)
            
            painter = QPainter(pixmap)
            x_offset = (24 - new_icon_width) // 2
            y_offset = (24 - new_icon_height) // 2
            painter.drawPixmap(x_offset, y_offset, rendered_pixmap)
            painter.end()
        except Exception as e:
            logging.warning(f"Failed to load or render lossless.svg: {e}")
    else:
        logging.warning(f"lossless.svg not found at: {icon_path}")
    icon_label.setPixmap(pixmap)
    layout.addWidget(icon_label)


    if is_hires:
        text_widget = ShimmerTag(text)
        text_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        text_widget.setFixedHeight(18)
    else:
        text_widget = QLabel(text)
        text_widget.setStyleSheet("color: #cccccc; font-size: 9pt; font-weight: bold;")
    layout.addWidget(text_widget)

    # 3. Atmos Icon
    if is_atmos:
        atmos_icon_label = QLabel()
        atmos_icon_path = resource_path('src/assets/atmos.svg')
        if os.path.exists(atmos_icon_path):
            try:
                with open(atmos_icon_path, 'rb') as f:
                    svg_bytes = f.read()

                new_icon_height = 14
                new_icon_width = int(new_icon_height * (95.0 / 24.0))
                
                atmos_icon_label.setFixedSize(new_icon_width, 24)
                atmos_pixmap = QPixmap(atmos_icon_label.size())
                atmos_pixmap.fill(Qt.GlobalColor.transparent)
                
                icon_color = QColor("#ffffff")
                rendered_pixmap = render_svg_tinted(svg_bytes, QSize(new_icon_width, new_icon_height), icon_color)

                painter = QPainter(atmos_pixmap)
                y_offset = (atmos_icon_label.height() - new_icon_height) // 2
                painter.drawPixmap(0, y_offset, rendered_pixmap)
                painter.end()

                atmos_icon_label.setPixmap(atmos_pixmap)
                layout.addWidget(atmos_icon_label)
            except Exception as e:
                logging.warning(f"Failed to load or render atmos.svg: {e}")
        else:
            logging.warning(f"atmos.svg not found at: {atmos_icon_path}")

    layout.addStretch()
    return container

class MarqueeLabel(QLabel):

    def __init__(self, text="", parent=None, hover_to_scroll=False, always_scroll=False, step_px=1, interval_ms=20, hover_delay_ms=600):
        super().__init__(text, parent)
        self._full_text = text or ""
        self._offset = 0
        self._need_scroll = False
        self._hover_to_scroll = hover_to_scroll
        self._always_scroll = always_scroll
        self._step_px = max(1, step_px)
        self._interval_ms = max(10, interval_ms)
        self._hover_delay_ms = hover_delay_ms
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._start_scrolling)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._gap_px = 30
        self.setToolTip(self._full_text)
        self._update_scroll_state()

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        super().setText(text)
        self.setToolTip(self._full_text)
        self._offset = 0
        self._update_scroll_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll_state()

    def enterEvent(self, event) -> None:
        if self._hover_to_scroll and self._need_scroll:
            self._hover_timer.start(self._hover_delay_ms)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_to_scroll:
            self._hover_timer.stop()
            self._stop_scrolling(reset=True)
        super().leaveEvent(event)

    def _text_metrics_width(self) -> int:
        fm = QFontMetrics(self.font())
        return fm.horizontalAdvance(self._full_text)

    def _update_scroll_state(self) -> None:
        if self.width() <= 0:
            self._need_scroll = False
            self._stop_scrolling(reset=True)
            return
        txt_w = self._text_metrics_width()
        self._need_scroll = txt_w > self.width()
        if self._always_scroll and self._need_scroll:
            self._start_scrolling()
        else:
            if not self._hover_to_scroll:
                self._stop_scrolling(reset=True)
        self.update()

    def _start_scrolling(self) -> None:
        if self._need_scroll and not self._timer.isActive():
            self._timer.start(self._interval_ms)

    def _stop_scrolling(self, reset=False) -> None:
        if self._timer.isActive():
            self._timer.stop()
        if reset:
            self._offset = 0
            self.update()

    def _tick(self) -> None:
        txt_w = self._text_metrics_width()
        if not self._need_scroll or txt_w <= 0:
            self._stop_scrolling(reset=True)
            return
        self._offset = (self._offset + self._step_px) % (txt_w + self._gap_px)
        self.update()

    def paintEvent(self, e: QPaintEvent) -> None:
        if not self._need_scroll or (not self._timer.isActive() and not self._always_scroll):
            return super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.rect()
        txt = self._full_text
        fm = QFontMetrics(self.font())
        txt_w = fm.horizontalAdvance(txt)
        x1 = -self._offset
        y = int((rect.height() + fm.ascent() - fm.descent()) / 2)
        painter.drawText(x1, y, txt)
        painter.drawText(x1 + txt_w + self._gap_px, y, txt)
        painter.end()

def _enable_label_wordwrap(widget: QWidget):
    for lab in widget.findChildren(QLabel):
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

class TrackItemWidget(QWidget):
    selection_changed = pyqtSignal(bool)
    play_requested = pyqtSignal(dict)
    def __init__(self, track_data, parent=None):
        super().__init__(parent)
        self.track_data = track_data
        self.track_id = track_data.get('trackData', {}).get('id')
        attrs = track_data.get('trackData', {}).get('attributes', {})
        self.track_url = attrs.get('url')
        self._is_selected = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        self.track_num_label = QLabel(str(attrs.get('trackNumber', '')))
        self.track_num_label.setFixedWidth(36)
        self.track_num_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.track_num_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.track_num_label)
        info_container = QWidget()
        info_container.setStyleSheet("background: transparent;")
        info_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_layout = QVBoxLayout(info_container)
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)
        title_container = QWidget()
        title_container.setStyleSheet("background: transparent;")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)
        title_text = attrs.get('name', 'Unknown Track')
        self.title_label = MarqueeLabel(title_text, hover_to_scroll=True, always_scroll=False, step_px=1, interval_ms=20, hover_delay_ms=600)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(self.title_label)
        if attrs.get('contentRating') == 'explicit':
            self.explicit_label = QLabel("E")
            self.explicit_label.setFixedSize(16, 16)
            self.explicit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.explicit_label.setStyleSheet("background-color: #555; color: #eee; border-radius: 2px; font-size: 10px; font-weight: bold;")
            title_layout.addWidget(self.explicit_label)
        title_layout.addStretch()
        self.artist_label = QLabel(attrs.get('artistName', 'Unknown Artist'))
        self.artist_label.setStyleSheet("color: #aaa; font-size: 9pt;")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(title_container)
        info_layout.addWidget(self.artist_label)
        layout.addWidget(info_container, 1)
        self.quality_widget_container = QWidget()
        self.quality_widget_container.setStyleSheet("background: transparent;")
        self.quality_widget_container.setFixedWidth(180)
        self.quality_widget_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        q_layout = QVBoxLayout(self.quality_widget_container)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.setSpacing(0)
        q_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.quality_widget_container)
        self.play_button = PlayButton(self)
        self.play_button.setFixedWidth(30)
        self.play_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.play_button)
        duration_ms = attrs.get('durationInMillis', 0)
        seconds = duration_ms // 1000
        duration_str = f"{seconds // 60}:{seconds % 60:02d}"
        self.duration_label = QLabel(duration_str)
        self.duration_label.setFixedWidth(56)
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.duration_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.duration_label)
        self.play_button.clicked.connect(self.on_play_clicked)
        self.setStyleSheet("""
            TrackItemWidget { background-color: transparent; border-radius: 4px; }
            TrackItemWidget[selected="true"] { background-color: #d60117; }
            TrackItemWidget[selected="true"] QLabel[low_res_quality="true"] { color: white; }
        """)
        self._update_label_styles()

    def on_play_clicked(self):
        attrs = self.track_data.get('trackData', {}).get('attributes', {})
        previews = attrs.get('previews', [])
        preview_url = previews[0]['url'] if previews else None
        if preview_url:
            flat_data = {
                'name': attrs.get('name'),
                'artist': attrs.get('artistName'),
                'previewUrl': preview_url,
                'appleMusicUrl': attrs.get('url'),
                'artworkUrl': attrs.get('artwork', {}).get('url')
            }
            self.play_requested.emit(flat_data)

    def set_playback_state(self, state):
        if hasattr(self, 'play_button'):
            self.play_button.setState(state)

    def _update_label_styles(self):
        if self._is_selected:
            self.title_label.setStyleSheet("font-weight: bold; color: white; background-color: transparent;")
            self.artist_label.setStyleSheet("color: white; background-color: transparent;")
            self.track_num_label.setStyleSheet("color: white; background-color: transparent;")
            self.duration_label.setStyleSheet("color: white; background-color: transparent;")
            if hasattr(self, 'explicit_label'):
                self.explicit_label.setStyleSheet("background-color: rgba(255,255,255,0.3); color: white; border-radius: 2px; font-size: 9px; font-weight: bold;")
        else:
            self.title_label.setStyleSheet("font-weight: bold; color: #e0e0e0; background-color: transparent;")
            self.artist_label.setStyleSheet("color: #aaa; font-size: 9pt; background-color: transparent;")
            self.track_num_label.setStyleSheet("color: #aaa; background-color: transparent;")
            self.duration_label.setStyleSheet("color: #aaa; background-color: transparent;")
            if hasattr(self, 'explicit_label'):
                self.explicit_label.setStyleSheet("background-color: #555; color: #eee; border-radius: 2px; font-size: 9px; font-weight: bold;")

    def isSelected(self):
        return self._is_selected

    def setSelected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.setProperty("selected", selected)
            if hasattr(self, 'play_button'):
                self.play_button.setParentSelected(selected)
            self._update_label_styles()
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
            self.selection_changed.emit(selected)

    def get_track_id(self):
        return self.track_id

    def mousePressEvent(self, event):
        if hasattr(self, 'play_button') and self.play_button.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        self.setSelected(not self.isSelected())
        super().mousePressEvent(event)

class TrackSelectionDialog(QDialog):
    play_requested = pyqtSignal(dict)
    check_qualities_requested = pyqtSignal(list)
    def __init__(self, album_data, parent=None):
        super().__init__(parent)
        self.album_data = album_data
        self.track_widgets = []
        album_attrs = self.album_data.get('albumData', {}).get('attributes', {})
        self.setWindowTitle(f"Select Tracks from '{album_attrs.get('name', 'Album')}'")
        self.setMinimumSize(560, 320)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.download_button = QPushButton("Download Selected")
        self.select_all_button = QPushButton("Select All")
        self.check_qualities_button = QPushButton("Check Qualities")
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet("""
            QPushButton { background-color: #e53935; color: white; border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #f44336; }
            QPushButton:pressed { background-color: #d32f2f; }
        """)
        self.download_button.clicked.connect(self.accept)
        self.select_all_button.clicked.connect(self.select_all_tracks)
        self.check_qualities_button.clicked.connect(self._on_check_qualities)
        self.close_button.clicked.connect(self.reject)
        self.header_widget = self._create_header(album_attrs)
        self.main_layout.addWidget(self.header_widget)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("QFrame { background-color: #555; height: 2px; }")
        self.main_layout.addWidget(line)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        self.scroll_content = QWidget()
        self.track_list_layout = QVBoxLayout(self.scroll_content)
        self.track_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.track_list_layout.setSpacing(0)
        scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(scroll_area)
        self.populate_tracks()
        self._fetch_artwork(album_attrs)
        QTimer.singleShot(0, self.adjust_dialog_size)

    def _on_check_qualities(self):
        self.check_qualities_button.setEnabled(False)
        self.check_qualities_button.setText("Checking...")
        tracks_to_probe = [w.track_data.get('trackData') for w in self.track_widgets if w.track_data.get('trackData')]
        self.check_qualities_requested.emit(tracks_to_probe)

    @pyqtSlot(list)
    def update_track_qualities(self, updated_tracks: list):
        self.check_qualities_button.setText("Check Qualities")
        self.check_qualities_button.setEnabled(True)
        for i, track_widget in enumerate(self.track_widgets):
            if i < len(updated_tracks):
                attrs = updated_tracks[i].get('attributes', {})
                if (layout := track_widget.quality_widget_container.layout()) is not None:
                    while layout.count():
                        item = layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                else:
                    layout = QVBoxLayout(track_widget.quality_widget_container)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                
                traits = set(attrs.get('audioTraits', []))
                sr = attrs.get('sampleRateHz')
                bd = attrs.get('bitDepth')
                if not bd:
                    if 'hi-res-lossless' in traits: bd = 24
                    elif 'lossless' in traits: bd = 16
                
                parts = []
                if isinstance(bd, int) and bd > 0: parts.append(f"{bd}B")
                if isinstance(sr, int) and sr > 0:
                    khz = sr / 1000.0
                    khz_text = f"{khz:.1f}" if abs(khz - int(khz)) > 1e-3 else f"{int(khz)}"
                    parts.append(f"{khz_text}kHz")

                if parts:
                    is_hires = (isinstance(bd, int) and bd >= 24 and isinstance(sr, int) and sr >= 96000)
                    quality_text = " . ".join(parts)
                    is_atmos = 'atmos' in traits
                    
                    quality_widget = _create_track_quality_widget(
                        quality_text,
                        is_hires=is_hires,
                        is_atmos=is_atmos
                    )
                    
                    if not is_hires:
                        q_layout = quality_widget.layout()
                        if q_layout and q_layout.count() > 1:
                            text_widget_item = q_layout.itemAt(1)
                            if text_widget_item and isinstance(text_widget_item.widget(), QLabel):
                                text_widget_item.widget().setProperty("low_res_quality", True)

                    _enable_label_wordwrap(quality_widget)
                    layout.addWidget(quality_widget)

    def update_playback_state(self, state, song_url):
        for widget in self.track_widgets:
            if not sip.isdeleted(widget):
                current_state = PlayButton.State.Stopped
                if widget.track_url == song_url:
                    current_state = state
                widget.set_playback_state(current_state)

    def _button_text_width(self, btn: QPushButton) -> int:
        fm = QFontMetrics(btn.font())
        return fm.horizontalAdvance(btn.text()) + 24

    def _set_button_widths_by_text(self):
        widths = [
            self._button_text_width(self.download_button),
            self._button_text_width(self.select_all_button),
            self._button_text_width(self.check_qualities_button),
            self._button_text_width(self.close_button),
        ]
        min_w = max(widths)
        for b in (self.download_button, self.select_all_button, self.check_qualities_button, self.close_button):
            b.setMinimumWidth(min_w)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def adjust_dialog_size(self):
        header_height = 90
        track_item_height = 45
        num_tracks = len(self.track_widgets)
        tracks_height = min(num_tracks * track_item_height, 420)
        margins = self.main_layout.contentsMargins()
        total_height = header_height + tracks_height + 60 + margins.top() + margins.bottom()
        final_height = max(360, min(total_height, 700))
        base_fixed = 36 + 180 + 30 + 56 + 48 + 20 # Adjusted for new container width
        max_title_width = 320
        if self.track_widgets:
            fm = QFontMetrics(QFont(self.font().family(), 10, QFont.Weight.Bold))
            for widget in self.track_widgets:
                track_name = widget.track_data.get('trackData', {}).get('attributes', {}).get('name', '')
                text_width = fm.horizontalAdvance(track_name)
                max_title_width = max(max_title_width, min(text_width, 520))
        self._set_button_widths_by_text()
        button_area_width = self.download_button.minimumWidth() * 2 + 20
        calculated_width = max_title_width + base_fixed + button_area_width
        screen_width = self.screen().availableGeometry().width()
        final_width = max(600, min(calculated_width, int(screen_width * 0.7)))
        self.resize(final_width, final_height)

    def _create_header(self, album_attrs):
        header_widget = QWidget()
        header_widget.setFixedHeight(90)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(15)
        self.art_label = QLabel()
        self.art_label.setFixedSize(60, 60)
        self.art_label.setStyleSheet("background-color: transparent;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setText("Loading...")
        header_layout.addWidget(self.art_label, 0, Qt.AlignmentFlag.AlignVCenter)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_label = MarqueeLabel(album_attrs.get('name', 'Unknown Album'), hover_to_scroll=False, always_scroll=True, step_px=1, interval_ms=20)
        title_label.setWordWrap(False)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        artist_label = QLabel(album_attrs.get('artistName', 'Unknown Artist'))
        artist_font = QFont()
        artist_font.setPointSize(9)
        artist_label.setFont(artist_font)
        artist_label.setStyleSheet("color: #ccc;")
        artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tracks = self.album_data.get('tracks', [])
        track_count = len(tracks)
        total_duration_ms = sum(t.get('trackData', {}).get('attributes', {}).get('durationInMillis', 0) for t in tracks)
        total_minutes = total_duration_ms // 1000 // 60
        meta_text = f"{track_count} tracks • {total_minutes} min"
        meta_label = QLabel(meta_text)
        meta_font = QFont()
        meta_font.setPointSize(8)
        meta_label.setFont(meta_font)
        meta_label.setStyleSheet("color: #aaa;")
        meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(title_label)
        info_layout.addWidget(artist_label)
        info_layout.addWidget(meta_label)
        header_layout.addLayout(info_layout, 1)
        button_container = QWidget()
        button_grid = QGridLayout(button_container)
        button_grid.setSpacing(5)
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.addWidget(self.download_button, 0, 0)
        button_grid.addWidget(self.select_all_button, 0, 1)
        button_grid.addWidget(self.check_qualities_button, 1, 0)
        button_grid.addWidget(self.close_button, 1, 1)
        header_layout.addWidget(button_container)
        return header_widget

    def _fetch_artwork(self, album_attrs):
        artwork_url = album_attrs.get('artwork', {}).get('url', '').replace('{w}', '120').replace('{h}', '120')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            self.worker.signals.error.connect(self._on_artwork_error)
            QThreadPool.globalInstance().start(self.worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            rounded = round_pixmap(scaled, 6)
            self.art_label.setPixmap(rounded)

    @pyqtSlot(str)
    def _on_artwork_error(self, error_str: str):
        self.art_label.setText("No Art")

    def populate_tracks(self):
        tracks = self.album_data.get('tracks', [])
        self.track_widgets.clear()
        while self.track_list_layout.count():
            item = self.track_list_layout.takeAt(0)
            if (widget := item.widget()) is not None:
                widget.deleteLater()
        disc_numbers = {t.get('trackData', {}).get('attributes', {}).get('discNumber', 1) for t in tracks}
        is_multi_disc = len(disc_numbers) > 1
        current_disc = -1
        for track_probe in tracks:
            attrs = track_probe.get('trackData', {}).get('attributes', {})
            disc_num = attrs.get('discNumber', 1)
            if is_multi_disc and disc_num != current_disc:
                disc_header = QLabel(f"Disc {disc_num}")
                disc_header.setStyleSheet("font-size: 11pt; margin-top: 10px; margin-bottom: 5px; border-bottom: 1px solid #444; padding-bottom: 5px;")
                disc_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.track_list_layout.addWidget(disc_header)
                current_disc = disc_num
            track_widget = TrackItemWidget(track_probe)
            track_widget.play_requested.connect(self.play_requested.emit)
            self.track_list_layout.addWidget(track_widget)
            self.track_widgets.append(track_widget)

    def select_all_tracks(self):
        all_selected = all(widget.isSelected() for widget in self.track_widgets)
        new_state = not all_selected
        for widget in self.track_widgets:
            widget.setSelected(new_state)
        self.select_all_button.setText("Deselect All" if new_state else "Select All")

    def get_selected_track_ids(self) -> list[str]:
        selected_ids = []
        for widget in self.track_widgets:
            if widget.isSelected():
                track_id = widget.get_track_id()
                if track_id:
                    selected_ids.append(track_id)
        return selected_ids

class TrackListingDialog(QDialog):
    def __init__(self, album_data, parent=None):
        super().__init__(parent)
        self.album_data = album_data
        album_attrs = self.album_data.get('albumData', {}).get('attributes', {})
        self.setWindowTitle(f"Tracks: {album_attrs.get('name', 'Unknown Album')}")
        self.setMinimumSize(560, 420)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        header_widget = self._create_header(album_attrs)
        self.main_layout.addWidget(header_widget)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.main_layout.addWidget(line)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        self.scroll_content = QWidget()
        self.track_list_layout = QVBoxLayout(self.scroll_content)
        self.track_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.track_list_layout.setSpacing(2)
        self.track_list_layout.setContentsMargins(5, 5, 5, 5)
        scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(scroll_area)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(button_box)
        self.populate_tracks(self.album_data.get('tracks', []))
        self._fetch_artwork(album_attrs)

    def _create_header(self, album_attrs):
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(15)
        self.art_label = QLabel()
        self.art_label.setFixedSize(120, 120)
        self.art_label.setStyleSheet("background-color: transparent;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setText("...")
        header_layout.addWidget(self.art_label, 0, Qt.AlignmentFlag.AlignTop)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        title_label = MarqueeLabel(album_attrs.get('name', 'Unknown Album'), hover_to_scroll=False, always_scroll=True, step_px=1, interval_ms=20)
        title_label.setWordWrap(False)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        artist_label = QLabel(album_attrs.get('artistName', 'Unknown Artist'))
        artist_font = QFont()
        artist_font.setPointSize(10)
        artist_label.setFont(artist_font)
        artist_label.setStyleSheet("color: #aaa;")
        artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tracks = self.album_data.get('tracks', [])
        total_duration_ms = sum(t.get('trackData', {}).get('attributes', {}).get('durationInMillis', 0) for t in tracks)
        total_seconds = total_duration_ms // 1000
        total_minutes = total_seconds // 60
        genre_list = album_attrs.get('genreNames', [])
        genre = genre_list[0] if genre_list else ''
        track_count = len(tracks)
        meta_text = f"{genre} • {track_count} tracks • {total_minutes}m"
        meta_label = QLabel(meta_text)
        meta_font = QFont()
        meta_font.setPointSize(10)
        meta_label.setFont(meta_font)
        meta_label.setStyleSheet("color: #aaa;")
        meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(title_label)
        info_layout.addWidget(artist_label)
        info_layout.addWidget(meta_label)
        info_layout.addStretch()
        header_layout.addLayout(info_layout, 1)
        return header_widget

    def _fetch_artwork(self, album_attrs):
        artwork_url = album_attrs.get('artwork', {}).get('url', '').replace('{w}', '240').replace('{h}', '240')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            self.worker.signals.error.connect(self._on_artwork_error)
            QThreadPool.globalInstance().start(self.worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            rounded = round_pixmap(scaled, 8)
            self.art_label.setPixmap(rounded)

    @pyqtSlot(str)
    def _on_artwork_error(self, error_str: str):
        self.art_label.setText("No Art")

    def populate_tracks(self, tracks):
        disc_numbers = {t.get('trackData', {}).get('attributes', {}).get('discNumber', 1) for t in tracks}
        is_multi_disc = len(disc_numbers) > 1
        current_disc = -1
        for track_probe in tracks:
            attrs = track_probe.get('trackData', {}).get('attributes', {})
            disc_num = attrs.get('discNumber', 1)
            if is_multi_disc and disc_num != current_disc:
                disc_header = QLabel(f"Disc {disc_num}")
                disc_header.setStyleSheet("font-size: 11pt; margin-top: 10px; margin-bottom: 5px; border-bottom: 1px solid #444; padding-bottom: 5px;")
                disc_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.track_list_layout.addWidget(disc_header)
                current_disc = disc_num
            track_widget = QWidget()
            track_layout = QHBoxLayout(track_widget)
            track_layout.setContentsMargins(5, 2, 5, 2)
            track_layout.setSpacing(10)
            track_num_label = QLabel(f"{attrs.get('trackNumber', 0):02d}")
            track_num_label.setFixedWidth(36)
            track_num_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            track_num_label.setStyleSheet("color: #aaa; font-size: 10pt;")
            track_layout.addWidget(track_num_label)
            title_label = MarqueeLabel(attrs.get('name', 'Unknown Track'), hover_to_scroll=True, always_scroll=False, step_px=1, interval_ms=20)
            title_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
            title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            track_layout.addWidget(title_label, 1)
            duration_ms = attrs.get('durationInMillis', 0)
            seconds = duration_ms // 1000
            duration_str = f"{seconds // 60}:{seconds % 60:02d}"
            duration_label = QLabel(duration_str)
            duration_label.setStyleSheet("color: #aaa; font-size: 10pt;")
            duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            duration_label.setFixedWidth(56)
            track_layout.addWidget(duration_label)
            self.track_list_layout.addWidget(track_widget)
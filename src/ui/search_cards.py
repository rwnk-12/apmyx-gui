import os
import sys
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QApplication, QMenu
)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThreadPool, QSize, Qt, QPointF, QEvent, QRectF, QRect
from PyQt6.QtGui import QPixmap, QMouseEvent, QBitmap, QPainter, QColor, QPen, QFontMetrics, QIcon, QPainterPath, QAction
from PyQt6.QtSvg import QSvgRenderer
from .search_widgets import LoadingSpinner, ImageFetcher, MarqueeLabel, round_pixmap, CustomCheckBox
from enum import Enum

def resource_path(relative_path):
    try:
        
        base_path = sys._MEIPASS
    except Exception:
       
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    return os.path.join(base_path, relative_path)

def render_svg_tinted(svg_bytes: bytes, size: QSize, color: QColor) -> QPixmap:
    renderer = QSvgRenderer(svg_bytes)
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size.width(), size.height()))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pm.rect(), color)
    p.end()
    return pm


HI_RES_TAG_ARTWORK_STYLESHEET = """
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe082, stop:1 #ffc107);
    color: black;
    border-radius: 2px;
    padding: 2px 5px;
    font-size: 7pt;
    font-weight: bold;
    border: 1px solid rgba(0, 0, 0, 0.15);
"""

class SelectionOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        art_rect = self.rect()

        ring_pen = QPen(QColor("#fd576b"), 2)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(art_rect.adjusted(1, 1, -1, -1), 12, 12)

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

class DownloadIconButton(QPushButton):
    State = Enum('State', ['Idle', 'Loading'])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Download")
        self.setStyleSheet("border: none;")
        self._is_hovering = False
        self._state = self.State.Idle
        self.spinner = LoadingSpinner(self)
        self.spinner.setGeometry(0, 0, 32, 32)
        self.spinner.stop()

    def setState(self, state):
        if self._state != state:
            self._state = state
            if self._state == self.State.Loading:
                self.setToolTip("Downloading...")
                self.spinner.start()
            else:
                self.setToolTip("Download")
                self.spinner.stop()
            self.update()

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
            painter.setBrush(QColor("#f5596d"))
        else:
            painter.setBrush(QColor(0, 0, 0, 200))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())

        if self._state == self.State.Idle:
            pen = QPen(Qt.GlobalColor.white)
            pen.setWidth(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            center_x = self.width() / 2
            center_y = self.height() / 2
            
            painter.drawLine(QPointF(center_x, center_y - 5), QPointF(center_x, center_y + 5))
            painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x - 4, center_y + 1))
            painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x + 4, center_y + 1))
            painter.drawLine(QPointF(center_x - 6, center_y + 8), QPointF(center_x + 6, center_y + 8))

class TracklistButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("View and select tracks")

        self.svg_pm_white = None
        icon_path = resource_path('src/assets/tracklist.svg')
        if os.path.exists(icon_path):
            try:
                with open(icon_path, 'rb') as f:
                    data = f.read()
                
                self.svg_pm_white = render_svg_tinted(data, QSize(20, 20), QColor("white"))
            except Exception as e:
                print(f"Failed to load or render SVG icon: {e}")

        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 200);
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                background-color: #f5596d;
            }
        """)

    def paintEvent(self, event):
    
        super().paintEvent(event)
        
       
        if self.svg_pm_white:
            p = QPainter(self)
            x = (self.width() - self.svg_pm_white.width()) // 2
            y = (self.height() - self.svg_pm_white.height()) // 2
            p.drawPixmap(x, y, self.svg_pm_white)

class InfoIconButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("View details")
        self.setStyleSheet("border: none;")
        self._is_hovering = False

    def enterEvent(self, e):
        self._is_hovering = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._is_hovering = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        from PyQt6.QtCore import QRectF
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg = QColor("#f5596d") if self._is_hovering else QColor(0, 0, 0, 200)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawEllipse(self.rect())

        margin = w * 0.25
        icon_size = w - (2 * margin)
        icon_rect = QRectF(margin, margin, icon_size, icon_size)
        
        ring_thickness = icon_size * 0.12
        
        ring_pen = QPen(Qt.GlobalColor.white, ring_thickness)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(icon_rect)

        
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Qt.GlobalColor.white)
        
        cx = icon_rect.center().x()
        
        
        dot_y = icon_rect.top() + icon_size * 0.28
        dot_radius = icon_size * 0.08
        p.drawEllipse(QPointF(cx, dot_y), dot_radius, dot_radius)
        
        
        stem_width = icon_size * 0.12
        stem_height = icon_size * 0.42
        stem_top = icon_rect.top() + icon_size * 0.48
        
        stem_rect = QRectF(
            cx - stem_width/2,
            stem_top,
            stem_width,
            stem_height
        )
        p.drawRoundedRect(stem_rect, stem_width/2, stem_width/2)
        
        p.end()

class SettingsButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(45, 45)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Settings")
        self.setStyleSheet("border: none; border-radius: 8px;")
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
            painter.drawRoundedRect(self.rect(), 8, 8)

        pen = QPen(QColor("#e0e0e0"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        center_y = self.height() / 2
        line_length = 16
        line_spacing = 5
        start_x = (self.width() - line_length) / 2

        painter.drawLine(int(start_x), int(center_y - line_spacing), int(start_x + line_length), int(center_y - line_spacing))
        painter.drawLine(int(start_x), int(center_y), int(start_x + line_length), int(center_y))
        painter.drawLine(int(start_x), int(center_y + line_spacing), int(start_x + line_length), int(center_y + line_spacing))

class MoreButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Download this item")
        self.setStyleSheet("border: none; border-radius: 12px;")
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

        painter.setBrush(QColor("#fd576b"))
        painter.setPen(Qt.PenStyle.NoPen)
        dot_radius = 1.5
        center_x = self.width() / 2
        center_y = self.height() / 2
        spacing = 5
        painter.drawEllipse(QPointF(center_x - spacing, center_y), dot_radius, dot_radius)
        painter.drawEllipse(QPointF(center_x, center_y), dot_radius, dot_radius)
        painter.drawEllipse(QPointF(center_x + spacing, center_y), dot_radius, dot_radius)

class PlayButton(QPushButton):
    State = Enum('State', ['Stopped', 'Loading', 'Playing', 'Paused'])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; border-radius: 12px;")
        self._state = self.State.Stopped
        self._is_hovering = False
        self._parent_is_selected = False
        self.spinner = LoadingSpinner(self)
        self.spinner.setGeometry(0, 0, 24, 24)
        self.spinner.stop()

    def setState(self, state):
        if self._state != state:
            self._state = state
            if self._state == self.State.Loading:
                self.spinner.start()
            else:
                self.spinner.stop()
            self.update()

    def setParentSelected(self, is_selected):
        if self._parent_is_selected != is_selected:
            self._parent_is_selected = is_selected
            self.update()

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

        if self._state in [self.State.Stopped, self.State.Paused, self.State.Playing]:
            icon_color = QColor("#FFFFFF") if self._parent_is_selected else QColor("#fd576b")
            pen = QPen(icon_color, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            if self._state == self.State.Stopped or self._state == self.State.Paused:
                self.setToolTip("Play Preview")
                path = QPainterPath()
                path.moveTo(self.width() * 0.4, self.height() * 0.3)
                path.lineTo(self.width() * 0.7, self.height() * 0.5)
                path.lineTo(self.width() * 0.4, self.height() * 0.7)
                path.closeSubpath()
                painter.fillPath(path, icon_color)
                painter.drawPath(path)
            elif self._state == self.State.Playing:
                self.setToolTip("Pause Preview")
                bar_width = self.width() * 0.1
                bar_height = self.height() * 0.4
                bar_y = (self.height() - bar_height) / 2
                bar1_x = self.width() * 0.35
                bar2_x = self.width() * 0.55
                painter.setBrush(icon_color)
                painter.drawRect(int(bar1_x), int(bar_y), int(bar_width), int(bar_height))
                painter.drawRect(int(bar2_x), int(bar_y), int(bar_width), int(bar_height))
        elif self._state == self.State.Loading:
            self.setToolTip("Loading...")

class DownloadButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Download this song")
        self.setStyleSheet("border: none; border-radius: 12px;")
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

        pen = QPen(QColor("#fd576b"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        center_x = self.width() / 2
        center_y = self.height() / 2
        
        painter.drawLine(QPointF(center_x, center_y - 5), QPointF(center_x, center_y + 5))
        painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x - 4, center_y + 1))
        painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x + 4, center_y + 1))
        painter.drawLine(QPointF(center_x - 6, center_y + 8), QPointF(center_x + 6, center_y + 8))

class SearchResultCard(QWidget):
    clicked = pyqtSignal(object)
    download_requested = pyqtSignal(object)
    tracklist_requested = pyqtSignal(object)
    info_requested = pyqtSignal(object)
    link_copied = pyqtSignal()
    selection_toggled = pyqtSignal(dict, bool)
    video_preview_requested = pyqtSignal(object)
    lyrics_download_requested = pyqtSignal(dict)
    artwork_download_requested = pyqtSignal(dict)
    copy_link_requested = pyqtSignal(dict)
    play_requested = pyqtSignal(dict)

    def __init__(self, result_data: dict, parent=None):
        super().__init__(parent)
        self.result_data = result_data
        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None
        self._is_selected = False
        self.setFixedSize(190, 250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        
        self.main_container = QWidget(self)
        self.main_container.setObjectName("SearchResultCardContainer")
        self.main_container.setStyleSheet("""
            #SearchResultCardContainer {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
            }
            #SearchResultCardContainer:hover {
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
        
        self.artwork_label = QLabel(self.artwork_container)
        self.artwork_label.setGeometry(0, 0, 180, 180)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setText("Loading...")
        
        self.artwork_label.setStyleSheet("background-color: transparent;")
        
        self.hover_mask = QLabel(self.artwork_container)
        self.hover_mask.setGeometry(0, 0, 180, 180)
        self.hover_mask.setStyleSheet("background-color: rgba(0,0,0,40); border-radius: 6px;")
        self.hover_mask.hide()

        self.selection_overlay = SelectionOverlay(self.artwork_container)
        self.selection_overlay.setGeometry(0, 0, 180, 180)
        self.selection_overlay.hide()

        self.hi_res_label = QLabel("HI-RES", self.artwork_container)
        self.hi_res_label.setStyleSheet(HI_RES_TAG_ARTWORK_STYLESHEET)
        self.hi_res_label.adjustSize()
        self.hi_res_label.move(8, 8)
        self.hi_res_label.hide()

        if "hi-res-lossless" in self.result_data.get('audioTraits', []):
            self.hi_res_label.show()

        self.download_button = DownloadIconButton(self.artwork_container)
        self.tracklist_button = TracklistButton(self.artwork_container)
        self.info_button = InfoIconButton(self.artwork_container)
        self.video_preview_button = PlayButton(self.artwork_container)
        self.video_preview_button.setFixedSize(32, 32)
        self.video_preview_button.setToolTip("Play Video Preview")
        self.play_button = PlayButton(self.artwork_container)
        self.play_button.setFixedSize(32, 32)
        
        self.action_spinner = LoadingSpinner(self.artwork_container)
        self.action_spinner.hide()
        self.active_button = None
        
        item_type = self.result_data.get('type')
        artwork_width = 180
        if item_type == 'songs':
            self.info_button.move(5, artwork_width - self.info_button.height() - 10)
            self.download_button.move(artwork_width - self.download_button.width() - 5, artwork_width - self.download_button.height() - 10)
            self.play_button.move(artwork_width - self.download_button.width() - self.play_button.width() - 10, artwork_width - self.download_button.height() - 10)
        elif item_type == 'music-videos':
            self.info_button.move(5, artwork_width - self.info_button.height() - 10)
            self.download_button.move(artwork_width - self.download_button.width() - self.video_preview_button.width() - 10, artwork_width - self.download_button.height() - 10)
            self.video_preview_button.move(artwork_width - self.video_preview_button.width() - 5, artwork_width - self.video_preview_button.height() - 10)
        else:
            self.info_button.move(5, artwork_width - self.info_button.height() - 10)
            self.download_button.move(artwork_width - self.download_button.width() - self.tracklist_button.width() - 10, artwork_width - self.download_button.height() - 10)
            self.tracklist_button.move(artwork_width - self.tracklist_button.width() - 5, artwork_width - self.tracklist_button.height() - 10)

        self.download_button.clicked.connect(self.on_download_button_clicked)
        self.tracklist_button.clicked.connect(self.on_tracklist_button_clicked)
        self.info_button.clicked.connect(self.on_info_button_clicked)
        self.video_preview_button.clicked.connect(self.on_video_preview_button_clicked)
        self.play_button.clicked.connect(self.on_play_button_clicked)
        
        self.download_button.hide()
        self.tracklist_button.hide()
        self.info_button.hide()
        self.video_preview_button.hide()
        self.play_button.hide()
        
        if item_type in ['albums', 'playlists', 'songs', 'music-videos']:
            self.artwork_container.installEventFilter(self)
        else:
            self.artwork_container.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.artwork_container)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(3, 3, 3, 0)
        text_layout.setSpacing(1)

        title_line_layout = QHBoxLayout()
        title_line_layout.setSpacing(4)
        self.title_label = MarqueeLabel(self.result_data.get('name', 'Unknown Title'))
        self.title_label.setStyleSheet("font-weight: bold;")
        title_line_layout.addWidget(self.title_label)

        if self.result_data.get('contentRating') == 'explicit':
            explicit_label = QLabel("E")
            explicit_label.setFixedSize(14, 14)
            explicit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            explicit_label.setStyleSheet("""
                QLabel {
                    background-color: #555;
                    color: #eee;
                    border-radius: 2px;
                    font-size: 9px;
                    font-weight: bold;
                }
            """)
            title_line_layout.addWidget(explicit_label)
        
        title_line_layout.addStretch()

        if item_type == 'playlists':
            bottom_text = self.result_data.get('curatorName', 'Playlist')
        elif item_type == 'artists':
            bottom_text = 'Artist'
        elif item_type == 'music-videos':
            bottom_text = f"{self.result_data.get('artist', 'Music Video')} • Music Video"
        else:
            bottom_text = self.result_data.get('artist', '')

        self.artist_label = MarqueeLabel(bottom_text)
        self.artist_label.setStyleSheet("color: #aaa;")

        text_layout.addLayout(title_line_layout)
        text_layout.addWidget(self.artist_label)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        self.main_container.installEventFilter(self)
        self._fetch_artwork()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3c2a2e, stop:1 #322427);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 4px;
                font-family: "Inter";
            }
            QMenu::item {
                background-color: transparent;
                color: #f0f0f0;
                padding: 8px 20px 8px 15px;
                border-radius: 4px;
                font-size: 9pt;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.1);
                margin: 4px 8px;
            }
            QMenu::icon {
                padding-left: 5px;
            }
        """)
        
        item_type = self.result_data.get('type')
        
        if item_type in ['songs', 'music-videos']:
            lyrics_action = QAction(QIcon.fromTheme("text-plain"), "Download Lyrics", self)
            lyrics_action.triggered.connect(lambda: self.lyrics_download_requested.emit(self.result_data))
            menu.addAction(lyrics_action)
        
        artwork_action = QAction(QIcon.fromTheme("image-x-generic"), "Download Artwork", self)
        artwork_action.triggered.connect(lambda: self.artwork_download_requested.emit(self.result_data))
        menu.addAction(artwork_action)
        
        menu.addSeparator()
        
        copy_link_action = QAction(QIcon.fromTheme("emblem-link"), "Copy Link", self)
        copy_link_action.triggered.connect(lambda: self.copy_link_requested.emit(self.result_data))
        menu.addAction(copy_link_action)
        
        menu.exec(event.globalPos())

    def isSelected(self) -> bool:
        return self._is_selected

    def setSelected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.selection_overlay.setVisible(selected)
            self.selection_toggled.emit(self.result_data, selected)

    def eventFilter(self, source, event):
        if source is self.main_container:
            if event.type() == QEvent.Type.Enter:
                self.title_label.start_animation()
                self.artist_label.start_animation()
            elif event.type() == QEvent.Type.Leave:
                self.title_label.stop_animation()
                self.artist_label.stop_animation()
        
        if source is self.artwork_container:
            item_type = self.result_data.get('type')
            if event.type() == QEvent.Type.Enter:
                self.hover_mask.show()
                self.info_button.show()
                if item_type == 'music-videos':
                    self.video_preview_button.show()
                    self.download_button.show()
                elif item_type == 'songs':
                    self.play_button.show()
                    self.download_button.show()
                else:
                    self.download_button.show()
                if item_type in ['albums', 'playlists']:
                    self.tracklist_button.show()
            elif event.type() == QEvent.Type.Leave:
                self.hover_mask.hide()
                self.download_button.hide()
                self.tracklist_button.hide()
                self.info_button.hide()
                self.video_preview_button.hide()
                self.play_button.hide()
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

    def on_play_button_clicked(self):
        self._set_active_button(self.play_button)
        self.play_requested.emit(self.result_data)

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
        artwork_url = self.result_data.get('artworkUrl')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
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
        
        if self.result_data.get('type') == 'artists':
            mask = QBitmap(scaled_pixmap.size())
            mask.fill(Qt.GlobalColor.white)
            painter = QPainter(mask)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.GlobalColor.black)
            painter.drawEllipse(scaled_pixmap.rect())
            painter.end()
            scaled_pixmap.setMask(mask)
            final_pixmap = scaled_pixmap
        else:
            final_pixmap = round_pixmap(scaled_pixmap, 12)
        
        self.artwork_label.setPixmap(final_pixmap)

    @pyqtSlot(str)
    def _on_load_error(self, error_str: str):
        self.artwork_label.setText("Load Error")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if self.result_data.get('type') == 'artists':
            self.clicked.emit(self)
            super().mousePressEvent(event)
            return

        if self.artwork_container.underMouse():
            local_pos = self.artwork_container.mapFrom(self, event.pos())
            for btn in [self.download_button, self.tracklist_button, self.info_button, self.video_preview_button, self.play_button]:
                if btn.isVisible() and btn.geometry().contains(local_pos):
                    super().mousePressEvent(event)
                    return

        self.setSelected(not self.isSelected())

class LoadingTile(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.spinner = LoadingSpinner(self)
        self.spinner.setFixedSize(32, 32)
        layout.addStretch()
        layout.addWidget(self.spinner)
        layout.addStretch()
        self.setFixedSize(190, 250)

    def start(self):
        self.spinner.start()

    def stop(self):
        self.spinner.stop()

class BaseListCard(QWidget):
    download_requested = pyqtSignal(object)
    tracklist_requested = pyqtSignal(object)
    selection_toggled = pyqtSignal(dict, bool)

    def __init__(self, result_data: dict, parent=None):
        super().__init__(parent)
        self.result_data = result_data
        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None
        self._is_selected = False
        
        self.main_container = QWidget()
        self.main_container.setObjectName("BaseListCardContainer")
        self.main_container.setStyleSheet("""
            #BaseListCardContainer {
                background-color: transparent;
                border-radius: 8px;
                border: 1px solid transparent;
                border-bottom: 1px solid #444;
            }
            #BaseListCardContainer:hover {
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid #555;
            }
            #BaseListCardContainer[selected="true"] {
                background-color: rgba(253, 87, 107, 0.2);
                border: 1px solid #fd576b;
            }
            #BaseListCardContainer QLabel {
                background-color: transparent;
            }
        """)

        layout = QHBoxLayout(self.main_container)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)

        self.artwork_label = QLabel()
        self.artwork_label.setFixedSize(50, 50)
        self.artwork_label.setStyleSheet("background-color: transparent;")
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setText("...")
        layout.addWidget(self.artwork_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        self.title_label = QLabel(self.result_data.get('name', 'Unknown Title'))
        self.title_label.setStyleSheet("font-size: 10pt; background-color: transparent;")
        
        self.details_label = QLabel()
        self.details_label.setStyleSheet("color: #aaa; font-size: 9pt; background-color: transparent;")

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.details_label)
        layout.addLayout(info_layout, 1)
        
        self._setup_buttons(layout)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(self.main_container)

    def _setup_buttons(self, layout):
        pass

    def _fetch_artwork(self):
        artwork_url = self.result_data.get('artworkUrl')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            self.worker.signals.error.connect(self._on_load_error)
            self.thread_pool.start(self.worker)
        else:
            self.artwork_label.setText("No Art")

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        
        scaled = pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        rounded = round_pixmap(scaled, 4)
        
        self.artwork_label.setPixmap(rounded)

    @pyqtSlot(str)
    def _on_load_error(self, error_str: str):
        self.artwork_label.setText("No Art")

    def isSelected(self) -> bool:
        return self._is_selected

    def setSelected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.main_container.setProperty("selected", selected)
            self.style().unpolish(self.main_container)
            self.style().polish(self.main_container)
            self.main_container.update()
            self.selection_toggled.emit(self.result_data, selected)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        for button in self.findChildren(QPushButton):
            if button.geometry().contains(self.main_container.mapFrom(self, event.pos())):
                super().mousePressEvent(event)
                return
        
        self.setSelected(not self.isSelected())

class SongListCard(BaseListCard):
    play_requested = pyqtSignal(dict)
    info_requested = pyqtSignal(object)
    lyrics_download_requested = pyqtSignal(dict)
    artwork_download_requested = pyqtSignal(dict)
    copy_link_requested = pyqtSignal(dict)

    def __init__(self, result_data: dict, parent=None):
        super().__init__(result_data, parent)
        self.setFixedHeight(60)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.main_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        info_layout = self.main_container.layout().itemAt(1).layout()
        info_layout.setSpacing(0)
        info_layout.setContentsMargins(0, 0, 0, 0)

        while info_layout.count():
            item = info_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            layout_item = item.layout()
            if layout_item:
                while layout_item.count():
                    nested_item = layout_item.takeAt(0)
                    if nested_item.widget():
                        nested_item.widget().deleteLater()

        self.title_label = MarqueeLabel(self.result_data.get('name', 'Unknown Title'))
        
        artist = self.result_data.get('artist', '')
        details_text = artist
        self.details_label = MarqueeLabel(details_text)

        font_weight = "600"
        self.title_label.setStyleSheet(f"font-size: 10pt; font-weight: {font_weight}; background-color: transparent; padding: 0px; margin: 0px;")
        self.details_label.setStyleSheet("color: #aaa; font-size: 8pt; font-weight: 600; background-color: transparent; padding: 0px; margin: 0px;")

        fm_title = QFontMetrics(self.title_label.font())
        self.title_label.setFixedHeight(fm_title.height())
        fm_details = QFontMetrics(self.details_label.font())
        self.details_label.setFixedHeight(fm_details.height())

        title_line_layout = QHBoxLayout()
        title_line_layout.setSpacing(4)
        title_line_layout.setContentsMargins(0, 0, 0, 0)
        title_line_layout.addWidget(self.title_label)

        if "hi-res-lossless" in self.result_data.get('audioTraits', []):
            hi_res_label = QLabel("HI-RES")
            hi_res_label.setObjectName("HiResTag")
            
            title_font = self.title_label.font()
            font_metrics = QFontMetrics(title_font)
            
            badge_font = title_font
            badge_font.setPointSize(max(6, int(title_font.pointSize() * 0.7)))
            hi_res_label.setFont(badge_font)
            
            badge_metrics = QFontMetrics(badge_font)
            badge_width = badge_metrics.horizontalAdvance("HI-RES") + 8
            badge_height = badge_metrics.height() + 2
            
            hi_res_label.setFixedSize(badge_width, badge_height)
            hi_res_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hi_res_label.setStyleSheet("""
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe082, stop:1 #ffc107);
                color: black;
                border-radius: 2px;
                font-weight: bold;
                border: 1px solid rgba(0, 0, 0, 0.15);
            """)
            
            title_line_layout.addWidget(hi_res_label)

        if self.result_data.get('contentRating') == 'explicit':
            explicit_label = QLabel("E")
            explicit_label.setFixedSize(14, 14)
            explicit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            explicit_label.setStyleSheet("""
                QLabel {
                    background-color: #555;
                    color: #eee;
                    border-radius: 2px;
                    font-size: 9px;
                    font-weight: bold;
                }
            """)
            title_line_layout.addWidget(explicit_label)
        
        title_line_layout.addStretch()

        info_layout.addLayout(title_line_layout)
        info_layout.addWidget(self.details_label)
        
        self.main_container.installEventFilter(self)

        self.action_spinner = LoadingSpinner(self.main_container)
        self.action_spinner.hide()
        self.active_button = None

        self._fetch_artwork()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3c2a2e, stop:1 #322427);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 4px;
                font-family: "Inter";
            }
            QMenu::item {
                background-color: transparent;
                color: #f0f0f0;
                padding: 8px 20px 8px 15px;
                border-radius: 4px;
                font-size: 9pt;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.1);
                margin: 4px 8px;
            }
            QMenu::icon {
                padding-left: 5px;
            }
        """)
        
        lyrics_action = QAction(QIcon.fromTheme("text-plain"), "Download Lyrics", self)
        lyrics_action.triggered.connect(lambda: self.lyrics_download_requested.emit(self.result_data))
        menu.addAction(lyrics_action)
        
        artwork_action = QAction(QIcon.fromTheme("image-x-generic"), "Download Artwork", self)
        artwork_action.triggered.connect(lambda: self.artwork_download_requested.emit(self.result_data))
        menu.addAction(artwork_action)
        
        menu.addSeparator()
        
        copy_link_action = QAction(QIcon.fromTheme("emblem-link"), "Copy Link", self)
        copy_link_action.triggered.connect(lambda: self.copy_link_requested.emit(self.result_data))
        menu.addAction(copy_link_action)
        
        menu.exec(event.globalPos())

    def set_playback_state(self, state):
        self.play_button.setState(state)

    def on_play_clicked(self):
        self.play_requested.emit(self.result_data)

    def eventFilter(self, source, event):
        if source is self.main_container:
            if event.type() == QEvent.Type.Enter:
                self.title_label.start_animation()
                self.details_label.start_animation()
            elif event.type() == QEvent.Type.Leave:
                self.title_label.stop_animation()
                self.details_label.stop_animation()
        return super().eventFilter(source, event)

    def _set_active_button(self, btn: QPushButton):
        self.active_button = btn
        try:
            btn.destroyed.connect(lambda: setattr(self, "active_button", None))
        except Exception:
            pass

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

    def on_download_clicked(self):
        self._set_active_button(self.download_button)
        self.download_requested.emit(self)

    def on_info_clicked(self):
        self._set_active_button(self.info_button)
        self.info_requested.emit(self)

    def _setup_buttons(self, layout):
        self.play_button = PlayButton(self)
        self.play_button.clicked.connect(self.on_play_clicked)
        layout.addWidget(self.play_button)

        self.download_button = DownloadButton(self)
        self.download_button.clicked.connect(self.on_download_clicked)
        layout.addWidget(self.download_button)

        self.info_button = InfoIconButton(self)
        self.info_button.setFixedSize(24, 24)
        self.info_button.clicked.connect(self.on_info_clicked)
        layout.addWidget(self.info_button)

class AlbumArtistListCard(BaseListCard):
    lyrics_download_requested = pyqtSignal(dict)
    artwork_download_requested = pyqtSignal(dict)
    copy_link_requested = pyqtSignal(dict)

    def __init__(self, result_data: dict, parent=None):
        super().__init__(result_data, parent)
        item_type = self.result_data.get('type', '')
        
        self.title_label.setStyleSheet("font-size: 10pt; font-weight: bold; background-color: transparent;")

        if item_type == 'albums':
            details = f"Album • {self.result_data.get('artist', '')}"
        elif item_type == 'artists':
            details = "Artist"
        else:
            details = ""
            
        self.details_label.setText(details)
        self._fetch_artwork()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3c2a2e, stop:1 #322427);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 4px;
                font-family: "Inter";
            }
            QMenu::item {
                background-color: transparent;
                color: #f0f0f0;
                padding: 8px 20px 8px 15px;
                border-radius: 4px;
                font-size: 9pt;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.1);
                margin: 4px 8px;
            }
            QMenu::icon {
                padding-left: 5px;
            }
        """)
        
        artwork_action = QAction(QIcon.fromTheme("image-x-generic"), "Download Artwork", self)
        artwork_action.triggered.connect(lambda: self.artwork_download_requested.emit(self.result_data))
        menu.addAction(artwork_action)
        
        menu.addSeparator()
        
        copy_link_action = QAction(QIcon.fromTheme("emblem-link"), "Copy Link", self)
        copy_link_action.triggered.connect(lambda: self.copy_link_requested.emit(self.result_data))
        menu.addAction(copy_link_action)
        
        menu.exec(event.globalPos())

    def on_download_clicked(self):
        self.download_requested.emit(self.result_data)

    def _setup_buttons(self, layout):
        item_type = self.result_data.get('type', '')
        if item_type == 'albums':
            self.tracklist_btn = TracklistButton(self)
            self.tracklist_btn.setFixedSize(24, 24)
            self.tracklist_btn.clicked.connect(lambda: self.tracklist_requested.emit(self.result_data))
            layout.addWidget(self.tracklist_btn)
        
        self.download_button = DownloadButton(self)
        self.download_button.clicked.connect(self.on_download_clicked)
        layout.addWidget(self.download_button)

class SongTableCard(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, result_data: dict, parent=None):
        super().__init__(parent)
        self.result_data = result_data
        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None
        
        self.main_container = QWidget()
        self.main_container.setObjectName("SongTableCardContainer")
  
        self.main_container.setStyleSheet("""
            #SongTableCardContainer {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 0px;
                border-bottom: 1px solid #444;
            }
            #SongTableCardContainer:hover {
                border: 1px solid #555;
                background-color: rgba(255, 255, 255, 10);
                border-radius: 8px;
            }
            #SongTableCardContainer QLabel {
                background-color: transparent;
            }
        """)
        
        layout = QHBoxLayout(self.main_container)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)

        self.artwork_label = QLabel()
        self.artwork_label.setFixedSize(40, 40)
        self.artwork_label.setStyleSheet("background-color: transparent;")
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setText("...")
        layout.addWidget(self.artwork_label)

        self.title_label = QLabel(self.result_data.get('name', 'Unknown Title'))
        self.title_label.setStyleSheet("font-weight: normal;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.title_label, 4)

        self.artist_label = QLabel(self.result_data.get('artist', ''))
        self.artist_label.setStyleSheet("color: #aaa;")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.artist_label, 3)

        self.album_label = QLabel(self.result_data.get('albumName', ''))
        self.album_label.setStyleSheet("color: #aaa;")
        self.album_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.album_label, 3)

        self.duration_label = QLabel(self.result_data.get('durationStr', ''))
        self.duration_label.setStyleSheet("color: #aaa;")
        layout.addWidget(self.duration_label)

        self.download_button = DownloadButton(self)
        self.download_button.clicked.connect(lambda: self.clicked.emit(self.result_data))
        layout.addWidget(self.download_button)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.addWidget(self.main_container)
        self.setFixedHeight(38)

        self._fetch_artwork()

    def _fetch_artwork(self):
        artwork_url = self.result_data.get('artworkUrl')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            self.worker.signals.error.connect(self._on_load_error)
            self.thread_pool.start(self.worker)
        else:
            self.artwork_label.setText("No Image")

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        
        scaled = pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        rounded = round_pixmap(scaled, 4)
        
        self.artwork_label.setPixmap(rounded)

    @pyqtSlot(str)
    def _on_load_error(self, error_str: str):
        self.artwork_label.setText("No Art")

    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)

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
        layout.setContentsMargins(5, 8, 5, 8)

        self.track_num_label = QLabel(str(attrs.get('trackNumber', '')))
        self.track_num_label.setFixedWidth(25)
        self.track_num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.track_num_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(0)
        
        title_line_layout = QHBoxLayout()
        title_line_layout.setSpacing(4)
        self.title_label = QLabel(attrs.get('name', 'Unknown Track'))
        title_line_layout.addWidget(self.title_label)

        if attrs.get('contentRating') == 'explicit':
            self.explicit_label = QLabel("E")
            self.explicit_label.setFixedSize(14, 14)
            self.explicit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_line_layout.addWidget(self.explicit_label)
        
        title_line_layout.addStretch()

        self.artist_label = QLabel(attrs.get('artistName', 'Unknown Artist'))
        info_layout.addLayout(title_line_layout)
        info_layout.addWidget(self.artist_label)
        layout.addLayout(info_layout)

        layout.addStretch()

        self.play_button = PlayButton(self)
        self.play_button.clicked.connect(self.on_play_clicked)
        layout.addWidget(self.play_button)

        duration_ms = attrs.get('durationInMillis', 0)
        seconds = duration_ms // 1000
        duration_str = f"{seconds // 60}:{seconds % 60:02d}"
        self.duration_label = QLabel(duration_str)
        layout.addWidget(self.duration_label)
        
        
        self.setStyleSheet("""
            TrackItemWidget {
                background-color: transparent;
                border-radius: 4px;
            }
            TrackItemWidget[selected="true"] {
                background-color: #fd576b;
            }
            TrackItemWidget QLabel {
                background-color: transparent;
            }
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
            self.title_label.setStyleSheet("font-weight: bold; color: white;")
            self.artist_label.setStyleSheet("color: white;")
            self.track_num_label.setStyleSheet("color: white;")
            self.duration_label.setStyleSheet("color: white;")
            if hasattr(self, 'explicit_label'):
                self.explicit_label.setStyleSheet("""
                    background-color: rgba(255,255,255,0.3);
                    color: white;
                    border-radius: 2px; font-size: 9px; font-weight: bold;
                """)
        else:
            self.title_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
            self.artist_label.setStyleSheet("color: #aaa; font-size: 9pt;")
            self.track_num_label.setStyleSheet("color: #aaa;")
            self.duration_label.setStyleSheet("color: #aaa;")
            if hasattr(self, 'explicit_label'):
                self.explicit_label.setStyleSheet("""
                    background-color: #555;
                    color: #eee;
                    border-radius: 2px; font-size: 9px; font-weight: bold;
                """)

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

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if hasattr(self, 'play_button') and self.play_button.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        self.setSelected(not self.isSelected())
        super().mousePressEvent(event)

class DiscographyCellWidget(QWidget):
    tracklist_requested = pyqtSignal(dict)

    def __init__(self, album_data: dict):
        super().__init__()
        self.setObjectName("DiscographyCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._selected = False
        self._label_widgets = []
        self._orig_label_styles = {}
        
        self.album_data = album_data
        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.checkbox = CustomCheckBox()
        self.checkbox.hide()
        layout.addWidget(self.checkbox)

        self.artwork_label = QLabel()
        self.artwork_label.setFixedSize(64, 64)
        self.artwork_label.setStyleSheet("background-color: transparent;")
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setText("...")
        layout.addWidget(self.artwork_label)

        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(1)
        
        attrs = self.album_data.get('attributes', {})
        
        name_label = QLabel(attrs.get('name', 'Unknown Album'))
        name_label.setStyleSheet("font-weight: bold; font-size: 10pt; margin: 0;")
        
        date_str = attrs.get('releaseDate', '')
        year = date_str[:4] if date_str else ''
        track_count = attrs.get('trackCount', 0)
        track_text = "track" if track_count == 1 else "tracks"
        details_text = f"{attrs.get('artistName', '')} • {year} • {track_count} {track_text}"
        details_label = QLabel(details_text)
        details_label.setStyleSheet("color: #bbb; font-size: 8.5pt; margin: 0;")
        info_layout.addWidget(name_label)
        info_layout.addWidget(details_label)
        info_widget.setMinimumWidth(1)
        layout.addWidget(info_widget, 1)

        self.tracklist_button = TracklistButton()
        self.tracklist_button.setToolTip("View and select tracks")
        self.tracklist_button.clicked.connect(self.on_tracklist_button_clicked)
        layout.addWidget(self.tracklist_button)

        self._collect_label_widgets()
        self.checkbox.toggled.connect(self.on_checkbox_toggled)
        
 
        self.setStyleSheet("""
            QWidget#DiscographyCell {
                background-color: transparent;
                border-radius: 6px;
                padding: 2px 5px;
            }
            QWidget#DiscographyCell:hover {
                background-color: rgba(255,255,255,0.04);
            }
            QWidget#DiscographyCell * {
                background-color: transparent;
            }
            QWidget#DiscographyCell CustomCheckBox,
            QWidget#DiscographyCell CustomCheckBox * {
                background-color: transparent;
            }
            QWidget#DiscographyCell[selected="true"] {
                background-color: #B83400;
                border-radius: 6px;
            }
            QWidget#DiscographyCell[selected="true"] QLabel {
                color: white;
                background-color: transparent;
            }
            QWidget#DiscographyCell[selected="true"] QCheckBox::indicator {
                border-color: white;
                background-color: rgba(255,255,255,0.20);
            }
        """)

        self._fetch_artwork()

    def _collect_label_widgets(self):
        self._label_widgets = self.findChildren(QLabel)
        self._orig_label_styles = {w: w.styleSheet() for w in self._label_widgets}

    def on_checkbox_toggled(self, checked: bool):
        self.set_selected(checked)

    def set_selected(self, checked: bool):
        self._selected = checked
        self.checkbox.setVisible(checked)
        self.setProperty("selected", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if checked:
            for lbl in self._label_widgets:
                base = self._orig_label_styles.get(lbl, "")
                sep = "" if (not base or base.strip().endswith(";")) else ";"
                lbl.setStyleSheet(f"{base}{sep} color: white; background-color: transparent;")
        else:
            for lbl in self._label_widgets:
                lbl.setStyleSheet(self._orig_label_styles.get(lbl, ""))

    def _fetch_artwork(self):
        attrs = self.album_data.get('attributes', {})
        artwork_url = attrs.get('artwork', {}).get('url')
        if not artwork_url:
            self.artwork_label.setText("No Image")
            return
        
        formatted_url = artwork_url.replace('{w}', '128').replace('{h}', '128')
            
        self.worker = ImageFetcher(formatted_url).auto_cancel_on(self)
        self.worker.signals.image_loaded.connect(self._set_artwork)
        self.worker.signals.error.connect(self._on_load_error)
        self.thread_pool.start(self.worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        
        scaled = pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        rounded = round_pixmap(scaled, 4)

        self.artwork_label.setPixmap(rounded)

    @pyqtSlot(str)
    def _on_load_error(self, error_msg: str):
        self.artwork_label.setText("Error")

    def on_tracklist_button_clicked(self):
        attrs = self.album_data.get('attributes', {})
        legacy_data = {
            'name': attrs.get('name'),
            'artist': attrs.get('artistName'),
            'date': attrs.get('releaseDate'),
            'artworkUrl': attrs.get('artwork', {}).get('url'),
            'appleMusicUrl': attrs.get('url')
        }
        self.tracklist_requested.emit(legacy_data)

    def is_checked(self):
        return self.checkbox.isChecked()

    def get_url(self):
        return self.album_data.get('attributes', {}).get('url')

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.tracklist_button.geometry().contains(event.pos()):
                self.checkbox.toggle()
        super().mousePressEvent(event)
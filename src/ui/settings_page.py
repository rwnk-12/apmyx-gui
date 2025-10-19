from __future__ import annotations

import os
import yaml
import requests
import copy
import re
import webbrowser
from typing import Dict, Any, List

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QObject, QRunnable, QThreadPool, QEvent, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QFormLayout, QLineEdit, QComboBox, QFileDialog, QSizePolicy, QSpacerItem,
    QDialog, QTabWidget, QMessageBox, QMenu, QApplication, QCheckBox, QGraphicsDropShadowEffect,
    QToolButton, QGridLayout, QStackedWidget, QButtonGroup
)
from PyQt6.QtGui import QIntValidator, QAction, QPainter, QColor, QPen, QFont

from .search_widgets import CustomCheckBox
from .search_cards import SettingsButton


ACCENT = "#fd576b"


class InfoButton(QPushButton):
    """A small, circular 'i' button to show informational popups."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none;")
        self.setToolTip("Click for more information")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isDown():
            painter.setBrush(QColor("#2a52be"))
        elif self.underMouse():
            painter.setBrush(QColor("#4169e1"))
        else:
            painter.setBrush(QColor("#3151a3"))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())

        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        font = QApplication.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "i")

class InfoPopup(QDialog):
    """A compact, custom-styled dialog for showing help text."""
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoPopup")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet("#InfoPopup QLabel { background-color: transparent; }")

    
        bg_widget = QFrame(self)
        bg_widget.setObjectName("InfoPopupBg")
        bg_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bg_widget.setFixedWidth(550)
        bg_widget.setStyleSheet("""
            QFrame#InfoPopupBg {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2e2e2e, stop:1 #1f1f1f);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        bg_widget.setGraphicsEffect(shadow)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(bg_widget)
        
        content_layout = QVBoxLayout(bg_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(12)

        # Title
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(title_label)

        # Message
        message_label = QLabel(message)
        message_font = QFont()
        message_font.setPointSize(10)
        message_font.setBold(False)
        message_label.setFont(message_font)
        message_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.RichText)
        message_label.setOpenExternalLinks(True)
        content_layout.addWidget(message_label)
        
        for lab in (title_label, message_label):
            lab.setAutoFillBackground(False)
            lab.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lab.setStyleSheet("background-color: transparent; color: %s;" %
                              ("white" if lab is title_label else "#c0c0c0"))
        
        content_layout.addSpacing(15)

       
        ok_button = QPushButton("OK")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setFixedHeight(34)
        ok_button_font = QApplication.font()
        ok_button_font.setPointSize(10)
        ok_button_font.setBold(True)
        ok_button.setFont(ok_button_font)
        ok_button.setStyleSheet(f"""
            QPushButton {{ 
                background-color: {ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{ 
                background-color: #e55366;
            }}
        """)
        ok_button.clicked.connect(self.accept)
        content_layout.addWidget(ok_button)
        
        self.setFixedSize(self.sizeHint())

    def showEvent(self, e: QEvent):
        super().showEvent(e)
        parent = self.parent() or self
        screen = parent.window().screen().availableGeometry()
        self.adjustSize()
        g = self.frameGeometry()
        center = screen.center()
        g.moveCenter(center)
     
        x = max(screen.left() + 12, min(g.left(), screen.right() - g.width() - 12))
        y = max(screen.top() + 12, min(g.top(), screen.bottom() - g.height() - 12))
        self.move(x, y)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)

class StorefrontDetectorSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

class StorefrontDetector(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = StorefrontDetectorSignals()

    def run(self):
        try:
            r = requests.get("http://ip-api.com/json/", timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "success":
                cc = (data.get("countryCode") or "").lower()
                if cc:
                    self.signals.finished.emit(cc)
                else:
                    self.signals.error.emit("Geolocation API did not return a country code.")
            else:
                self.signals.error.emit(f"Geolocation API error: {data.get('message','Unknown API error')}")
        except Exception as e:
            self.signals.error.emit(str(e))



class SettingsPage(QWidget):
    settings_applied = pyqtSignal(dict)
    back_requested = pyqtSignal()
    menu_requested = pyqtSignal()

    DEFAULTS: Dict[str, Any] = {
        'media-user-token': "", 'authorization-token': '', 'language': '',
        'lrc-type': 'lyrics', 'lrc-format': 'lrc', 'embed-lrc': True,
        'save-lrc-file': True, 'save-artist-cover': False, 'save-animated-artwork': False,
        'emby-animated-artwork': False, 'embed-cover': True, 'cover-size': '5000x5000',
        'cover-format': 'jpg', 'alac-save-folder': 'AM-DL downloads',
        'atmos-save-folder': 'AM-DL-Atmos downloads', 'aac-save-folder': 'AM-DL-AAC downloads',
        'mv-save-folder': 'AM-DL downloads/Music Videos',
        'max-memory-limit': 256, 'decrypt-m3u8-port': '127.0.0.1:10020',
        'get-m3u8-port': '127.0.0.1:20020', 'get-m3u8-from-device': True,
        'get-m3u8-mode': 'hires', 'aac-type': 'aac-lc', 'alac-max': 192000,
        'atmos-max': 2768, 'limit-max': 200, 'album-folder-format': '{AlbumName}',
        'playlist-folder-format': '{PlaylistName}', 'song-file-format': '{SongNumber}. {SongName}',
        'artist-folder-format': '{UrlArtistName}', 'explicit-choice': '[E]',
        'clean-choice': '[C]', 'apple-master-choice': '[M]',
        'use-songinfo-for-playlist': False, 'dl-albumcover-for-playlist': False,
        'mv-audio-type': 'atmos', 'mv-max': 2160, 'storefront': '',
        'tag-options': {
            'write-title': True, 'write-artist': True, 'write-artist-sort': False,
            'write-album': True, 'write-album-sort': False, 'write-album-artist': True,
            'write-album-artist-sort': False, 'write-composer': True, 'write-composer-sort': False,
            'write-genre': True, 'write-isrc': True, 'write-upc': True, 'write-date': True,
            'write-copyright': True, 'write-publisher': True, 'write-disc-track': True,
            'write-lyrics': True, 'write-cover': True, 'delete-sort-on-write': True,
            'use-mp4box-artist': False
        }
    }

    PARTIAL_RESET_KEYS: List[str] = [
        'decrypt-m3u8-port', 'get-m3u8-port', 'get-m3u8-from-device', 'get-m3u8-mode',
        'lrc-type', 'lrc-format', 'embed-lrc', 'save-lrc-file', 'save-artist-cover',
        'save-animated-artwork', 'emby-animated-artwork', 'embed-cover', 'cover-size',
        'cover-format', 'album-folder-format', 'playlist-folder-format', 'song-file-format',
        'artist-folder-format', 'explicit-choice', 'clean-choice', 'apple-master-choice',
        'use-songinfo-for-playlist', 'dl-albumcover-for-playlist',
        'mv-audio-type', 'mv-max'
    ]

    CATEGORIES = {
        "General": [
            'storefront', 'media-user-token', 'authorization-token', 'language',
            'alac-save-folder', 'atmos-save-folder', 'aac-save-folder', 'mv-save-folder'
        ],
        "Naming Formats": [
            'album-folder-format', 'song-file-format',
            'artist-folder-format', 'explicit-choice', 'clean-choice', 'apple-master-choice'
        ],
        "Playlist Settings": [
            'playlist-folder-format', 'use-songinfo-for-playlist', 'dl-albumcover-for-playlist'
        ],
        "Artwork": [
            'embed-cover', 'cover-size', 'cover-format', 'save-artist-cover',
            'save-animated-artwork', 'emby-animated-artwork'
        ],
        "Lyrics": [
            'embed-lrc', 'save-lrc-file', 'lrc-type', 'lrc-format'
        ],
        "Audio Quality": [
            'get-m3u8-mode', 'aac-type', 'alac-max', 'atmos-max'
        ],
        "Music Video Settings": [
            'mv-audio-type', 'mv-max'
        ],
        "Metadata Tagging": [
            'tag-options.write-title', 'tag-options.write-artist', 'tag-options.write-artist-sort',
            'tag-options.write-album', 'tag-options.write-album-sort', 'tag-options.write-album-artist',
            'tag-options.write-album-artist-sort', 'tag-options.write-composer', 'tag-options.write-composer-sort',
            'tag-options.write-genre', 'tag-options.write-isrc', 'tag-options.write-upc', 'tag-options.write-date',
            'tag-options.write-copyright', 'tag-options.write-publisher', 'tag-options.write-disc-track',
            'tag-options.write-lyrics', 'tag-options.write-cover', 'tag-options.delete-sort-on-write',
            'tag-options.use-mp4box-artist'
        ],
        "Advanced": [
            'max-memory-limit', 'limit-max', 'decrypt-m3u8-port', 'get-m3u8-port', 'get-m3u8-from-device'
        ]
    }

  
    CATEGORY_ORDER: list[str] = [
        "General",
        "Naming Formats",
        "Audio Quality",
        "Artwork",
        "Lyrics",
        "Metadata Tagging",
        "Playlist Settings",
        "Music Video Settings",
        "Advanced",
    ]

    OPTIONS = {
        'aac-type': ['aac-lc', 'aac', 'aac-binaural', 'aac-downmix'],
        'cover-format': ['jpg', 'png', 'original'],
        'alac-max': ['192000', '96000', '48000', '44100'],
        'atmos-max': ['2768', '2448'],
        'lrc-type': ['lyrics', 'syllable-lyrics'],
        'lrc-format': ['lrc', 'ttml'],
        'mv-audio-type': ['atmos', 'ac3', 'aac'],
        'mv-max': ['2160', '1080', '720', '480']
    }

    PLACEHOLDERS = {
        'album-folder-format': ['{AlbumId}', '{AlbumName}', '{ArtistName}', '{ReleaseDate}', '{ReleaseYear}', '{UPC}', '{Copyright}', '{Quality}', '{Codec}', '{Tag}', '{RecordLabel}'],
        'playlist-folder-format': ['{PlaylistId}', '{PlaylistName}', '{ArtistName}', '{Quality}', '{Codec}', '{Tag}'],
        'song-file-format': ['{SongId}', '{SongNumber}', '{SongName}', '{DiscNumber}', '{TrackNumber}', '{Quality}', '{Codec}', '{Tag}'],
        'artist-folder-format': ['{ArtistId}', '{ArtistName}', '{UrlArtistName}']
    }

    HELP_TEXT = {
        'storefront': {'tip': "Your 2-letter Apple Music region code (e.g., 'us', 'gb').", 'info_title': "About Storefront", 'info_body': "The Storefront <b>must</b> match your Apple account's country. An incorrect code can cause errors, especially with lyrics or region-specific content. Use 'Detect' to find it automatically from your IP address."},
        'media-user-token': {
            'tip': "Your personal Apple Music authentication token.", 
            'info_title': "Media User Token Guide", 
            'info_body': """
                <div style="text-align: left; line-height: 1.5;">
                <b>For Chrome:</b><br>
                1. Install the <a href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc?pli=1" style="color: #fd576b; text-decoration: none;">Get cookies.txt LOCALLY</a> extension.<br>
                2. Open the Apple Music website and log in to your account.<br>
                3. Click the extension icon and then the export button to save the cookies.txt file.<br>
                4. Open the file, find the line for "media-user-token", and copy the long value.<br>
                5. Paste the value into this field.<br><br>
                <b>For Firefox:</b><br>
                1. Install the <a href="https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/" style="color: #fd576b; text-decoration: none;">Export Cookies</a> extension.<br>
                2. Open the Apple Music website and log in to your account.<br>
                3. Click the extension icon and choose to export cookies for music.apple.com.<br>
                4. Open the saved file, find the line for "media-user-token", and copy the long value.<br>
                5. Paste the value into this field.
                </div>
            """
        },
        'authorization-token': {'tip': "Optional bearer token for some API requests."},
        'album-folder-format': {'tip': "Define the folder structure for downloaded albums."},
        'playlist-folder-format': {'tip': "Define the folder structure for downloaded playlists."},
        'song-file-format': {'tip': "Define the file naming scheme for downloaded songs."},
        'artist-folder-format': {'tip': "Define artist folder structure. Leave blank to directly save in folder without making Artist Folder."},
        'decrypt-m3u8-port': {'tip': "Local port used by the backend for decryption.", 'info_title': "Decryption Port", 'info_body': "The backend downloader uses this port for decrypting HLS streams. Change this only if it conflicts with another application on your system."},
        'get-m3u8-port': {'tip': "Local port used by the backend for fetching manifests."},
        'alac-max': {'tip': "Maximum sample rate for ALAC (lossless) downloads."},
        'atmos-max': {'tip': "Maximum bitrate for Dolby Atmos downloads."},
        'explicit-choice': {'tip': "Tag for explicit content. Leave blank to disable."},
        'clean-choice': {'tip': "Tag for clean content. Leave blank to disable."},
        'apple-master-choice': {'tip': "Tag for Apple Digital Masters. Leave blank to disable."},
        'aac-type': {'info_title': "AAC Audio Type", 'info_body': "aac-lc: Standard, high-quality stereo. Best for most users.\n\naac-binaural: Special mix for Spatial Audio on headphones.\n\naac-downmix: A stereo version derived from a Dolby Atmos mix."},
        'lrc-format': {'tip': "Select lyrics format. Note: TTML format cannot be embedded into audio files."}
    }

    def __init__(self, config_path='config.yaml', parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.thread_pool = QThreadPool.globalInstance()
        self.config: Dict[str, Any] = {}
        self.original: Dict[str, Any] = {}
        self.widgets: Dict[str, QWidget] = {}
        self.form_layouts: Dict[str, QFormLayout] = {}
        self._dirty = False

        self._load_config()
        self._build_ui()
        self._populate_panes()
        self._apply_styles()
        self._wire_actions()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._normalize_sizes)

    def _normalize_sizes(self):
        if self.layout():
            self.layout().activate()
        self.updateGeometry()
        for widget in self.widgets.values():
            if isinstance(widget, (QLineEdit, QComboBox)):
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _build_ui(self):
        self.setObjectName("SettingsPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

     
        self.hero = QWidget()
        self.hero.setObjectName("SettingsHero")
        hero_lay = QHBoxLayout(self.hero)
        hero_lay.setContentsMargins(20, 20, 20, 20)
        hero_lay.setSpacing(15)

        self.menu_btn = SettingsButton(self.hero)
        self.menu_btn.setToolTip("Menu")
        hero_lay.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignLeft)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("Settings")
        title_label.setObjectName("SettingsTitle")
        subtitle_label = QLabel("Configure downloads, quality, paths, and more.")
        subtitle_label.setObjectName("SettingsSubtitle")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        hero_lay.addLayout(title_box, 1)
        root.addWidget(self.hero)

   
        main_content = QWidget()
        main_layout = QHBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

    
        self.nav_pane = QFrame()
        self.nav_pane.setObjectName("NavPane")
        self.nav_pane.setFixedWidth(220)
        nav_layout = QVBoxLayout(self.nav_pane)
        nav_layout.setContentsMargins(10, 15, 10, 10)
        nav_layout.setSpacing(6)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)
        main_layout.addWidget(self.nav_pane)

     
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("Separator")
        main_layout.addWidget(separator)

    
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack, 1)
        root.addWidget(main_content, 1)

 
        self.bottom = QFrame()
        self.bottom.setObjectName("BottomBar")
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addStretch()
        self.reset_btn = QPushButton("Reset to Defaults")
        self.cancel_btn = QPushButton("Cancel")
        self.apply_btn = QPushButton("Apply")
        self.save_btn = QPushButton("Save")
        for b in (self.reset_btn, self.cancel_btn, self.apply_btn, self.save_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bl.addWidget(b)
        
        self.apply_btn.hide()
        self.save_btn.setText("Save")
        self.save_btn.setToolTip("Save changes and close Settings")
        root.addWidget(self.bottom)

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget#SettingsPage {{ 
                background-color: #262626; 
                color: #e0e0d0;
            }}
            QFrame#NavPane {{
                background-color: #2a2a2a;
            }}
            QFrame#Separator {{
                background-color: #3a3a3a;
            }}
            QFrame {{ background: transparent; }}
            QWidget#SettingsHero {{
                background-color: #2a2a2a;
                border-bottom: 1px solid #3a3a3a;
            }}
            QLabel#SettingsTitle {{
                font-size: 24pt;
                font-weight: 800;
                color: white;
                background: transparent;
            }}
            QLabel#SettingsSubtitle {{
                font-size: 9.5pt;
                color: #b0b0b0;
                font-weight: normal;
                background: transparent;
            }}
            /* Navigation Buttons */
            QFrame#NavPane QPushButton {{
                text-align: left;
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
                background-color: transparent;
                color: #c0c0c0;
                font-weight: bold;
            }}
            QFrame#NavPane QPushButton:hover {{
                background-color: #383838;
                color: white;
            }}
            QFrame#NavPane QPushButton:checked {{
                background-color: #d60117;
                color: white;
            }}
            /* General Controls */
            QPushButton {{
                background-color: #3e3e3e; 
                border: 1px solid #555;
                border-radius: 6px; 
                padding: 6px 14px; 
                color: #eee;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #4a4a4a; }}
            QLineEdit, QComboBox {{
                background-color: #2b2b2b; 
                border: 1px solid #444;
                border-radius: 6px; 
                padding: 7px;
                font-weight: bold;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {ACCENT};
            }}
            QComboBox::drop-down {{ border: none; }}
            QLabel#TipLabel, QLabel#PreviewLabel {{ 
                color: #bbb; 
                font-size: 8.5pt;
                font-weight: normal;
            }}
            QLabel#SettingLabel {{
                font-weight: bold;
                color: #e0e0e0;
            }}
            QLabel#SubheaderLabel {{
                font-size: 10pt;
                font-weight: bold;
                color: {ACCENT};
                padding-top: 10px;
                padding-bottom: 4px;
            }}
            QFrame#BottomBar {{
                background-color: #2a2a2a;
                border-top: 1px solid #3a3a3a;
            }}
            QScrollArea {{ border: none; }}
            QLineEdit[alert="true"] {{
                border: 1.5px solid #d60117;
            }}
            QLineEdit[alert="true"]:focus {{
                border: 1.5px solid #d60117;
            }}
        """)
        
        for btn in (self.save_btn, self.apply_btn):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #d60117;
                    border:none;
                    color:white;
                    font-weight:bold;
                    padding: 6px 16px;
                }} 
                QPushButton:hover{{
                    background-color: #e62237;
                }}
            """)

    def _wire_actions(self):
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        self.reset_btn.clicked.connect(self._on_reset)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.apply_btn.clicked.connect(self._on_apply)
        self.save_btn.clicked.connect(self._on_save)
        self.nav_button_group.idClicked.connect(self.content_stack.setCurrentIndex)

    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
        
        merged = copy.deepcopy(self.DEFAULTS)
        for key, value in data.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update(value)
            else:
                merged[key] = value

        self.config = merged
        self.original = copy.deepcopy(merged)

    def _iter_category_names_in_order(self) -> list[str]:
        base = list(self.CATEGORIES.keys())
        ordered = [c for c in self.CATEGORY_ORDER if c in self.CATEGORIES]
        tail = [c for c in base if c not in ordered]
        return ordered + tail

    def _populate_panes(self):
        nav_layout = self.nav_pane.layout()
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            widget.deleteLater()
        for button in self.nav_button_group.buttons():
            self.nav_button_group.removeButton(button)
            button.deleteLater()

        self.widgets.clear()
        self.form_layouts.clear()

        for cat_name in self._iter_category_names_in_order():
            nav_button = QPushButton(cat_name)
            nav_button.setCheckable(True)
            nav_button.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_layout.addWidget(nav_button)
            
            page_content = self._create_category_page(cat_name)
            
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(page_content)
            
            page_index = self.content_stack.addWidget(scroll_area)
            self.nav_button_group.addButton(nav_button, page_index)

        if self.nav_button_group.buttons():
            self.nav_button_group.buttons()[0].setChecked(True)
            self.content_stack.setCurrentIndex(0)

    def _create_subheader(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SubheaderLabel")
        return label

    def _create_category_page(self, cat_name: str) -> QWidget:
        keys = self.CATEGORIES[cat_name]
        
        page_widget = QWidget()
        page_layout = QVBoxLayout(page_widget)
        page_layout.setContentsMargins(25, 20, 25, 20)
        page_layout.setSpacing(15)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if cat_name == "Metadata Tagging":
            presets_layout = QHBoxLayout()
            presets_layout.setSpacing(10)
            presets_layout.addWidget(QLabel("<b>Presets:</b>"))
            basic_btn = QPushButton("Basic")
            detailed_btn = QPushButton("Detailed")
            full_btn = QPushButton("Full")
            for btn in (basic_btn, detailed_btn, full_btn):
                presets_layout.addWidget(btn)
            presets_layout.addStretch()
            page_layout.addLayout(presets_layout)

            basic_btn.clicked.connect(lambda: self._apply_metadata_preset('basic'))
            detailed_btn.clicked.connect(lambda: self._apply_metadata_preset('detailed'))
            full_btn.clicked.connect(lambda: self._apply_metadata_preset('full'))

            grid_layout = QGridLayout()
            grid_layout.setSpacing(10)
            grid_layout.setColumnStretch(1, 1)
            grid_layout.setColumnStretch(3, 1)
            
            nested_bool_keys = [k for k in keys if '.' in k and isinstance(self._get_default_value(k), bool)]
            
            num_rows = (len(nested_bool_keys) + 1) // 2
            for i, key in enumerate(nested_bool_keys):
                checkbox, label_widget = self._make_field_widget(key)
                row = i % num_rows
                col = (i // num_rows) * 2
                grid_layout.addWidget(label_widget, row, col, Qt.AlignmentFlag.AlignRight)
                grid_layout.addWidget(checkbox, row, col + 1)
            page_layout.addLayout(grid_layout)
        else:
            form_layout = QFormLayout()
            form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form_layout.setHorizontalSpacing(15)
            form_layout.setVerticalSpacing(12)
            self.form_layouts[cat_name] = form_layout

            if cat_name == "General":
                form_layout.addRow(self._create_subheader("Credentials & Region"))
            elif cat_name == "Naming Formats":
                form_layout.addRow(self._create_subheader("Folder & File Naming"))

            for key in keys:
                if key == 'alac-save-folder' and cat_name == "General":
                    form_layout.addRow(self._create_subheader("Save Locations"))
                
                field_widget, label_widget = self._make_field_widget(key)
                form_layout.addRow(label_widget, field_widget)
            page_layout.addLayout(form_layout)
        
        return page_widget

    def _get_config_value(self, key: str):
        if '.' in key:
            parent_key, child_key = key.split('.')
            return self.config.get(parent_key, {}).get(child_key)
        return self.config.get(key)

    def _get_default_value(self, key: str):
        if '.' in key:
            parent_key, child_key = key.split('.')
            return self.DEFAULTS.get(parent_key, {}).get(child_key)
        return self.DEFAULTS.get(key)

    def _make_field_widget(self, key: str):
        value = self._get_config_value(key)
        default_value = self._get_default_value(key)
        help_data = self.HELP_TEXT.get(key, {})
        tip_text = help_data.get('tip', '')
        info_title = help_data.get('info_title')
        info_body = help_data.get('info_body')
        
        label_text = key.split('.')[-1].replace('-', ' ').replace('_', ' ').title()
        
        label_container = QHBoxLayout()
        label_container.setContentsMargins(0,0,0,0)
        label_container.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label_container.setSpacing(5)
        label_widget = QLabel(label_text)
        label_widget.setObjectName("SettingLabel")
        label_container.addWidget(label_widget)
        
     
        if info_title and info_body and key not in self.CATEGORIES["Playlist Settings"]:
            info_btn = InfoButton()
            info_btn.clicked.connect(lambda _, t=info_title, b=info_body: self._show_info_popup(t, b))
            label_container.addWidget(info_btn)
        
        label_wrapper = QWidget()
        label_wrapper.setLayout(label_container)

        if isinstance(default_value, bool):
            checkbox = CustomCheckBox("") 
            checkbox.setChecked(bool(value))
            checkbox.stateChanged.connect(self._mark_dirty)
            self.widgets[key] = checkbox
            return checkbox, label_wrapper

        field_container = QVBoxLayout()
        field_container.setSpacing(4)
        
        if key in self.OPTIONS:
            widget = QComboBox()
            widget.addItems(self.OPTIONS[key])
            widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(self._mark_dirty)
            widget.setProperty("coerce_int", key in ("alac-max", "atmos-max", "mv-max"))
            field_container.addWidget(widget)
        else:
            widget = QLineEdit(str(value or ''))
            widget.textChanged.connect(self._mark_dirty)
            if isinstance(default_value, int):
                widget.setValidator(QIntValidator())
            
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            row_layout.addWidget(widget, 1)

            if key == 'storefront':
                widget.setMaxLength(2)
                detect = QPushButton("Detect")
                detect.setFixedWidth(70)
                detect.clicked.connect(lambda: self._show_storefront_detect_warning(widget, detect))
                row_layout.addWidget(detect)
            elif key.endswith('-save-folder'):
                browse = QPushButton("Browse…")
                browse.clicked.connect(lambda _, le=widget: self._browse_dir_into(le))
                row_layout.addWidget(browse)
            
            field_container.addLayout(row_layout)

        self.widgets[key] = widget

        if tip_text:
            tip_label = QLabel(tip_text)
            tip_label.setObjectName("TipLabel")
            field_container.addWidget(tip_label)

        if key in self.PLACEHOLDERS:
            chips_widget = QWidget()
            chips_layout = QHBoxLayout(chips_widget)
            chips_layout.setContentsMargins(0, 5, 0, 0)
            chips_layout.setSpacing(6)
            chips_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            
            for token in self.PLACEHOLDERS[key]:
                chip = QPushButton(token)
                chip.setStyleSheet("padding: 4px 9px; border-radius: 11px; font-size: 8.5pt; background-color: #3a3a3a; border: none; font-weight: bold;")
                chip.clicked.connect(lambda _, t=token: self._copy_to_clipboard(t))
                chips_layout.addWidget(chip)
            chips_layout.addStretch()
            field_container.addWidget(chips_widget)

        container_widget = QWidget()
        container_widget.setLayout(field_container)
        return container_widget, label_wrapper

    def _update_naming_preview(self, key: str, text: str, label: QLabel):
  
        pass

    def _apply_metadata_preset(self, preset: str):
        presets = {
            'basic': ['write-title', 'write-artist', 'write-album', 'write-album-artist', 'write-genre', 'write-date', 'write-disc-track', 'write-cover'],
            'detailed': ['write-title', 'write-artist', 'write-album', 'write-album-artist', 'write-composer', 'write-genre', 'write-isrc', 'write-upc', 'write-date', 'write-copyright', 'write-publisher', 'write-disc-track', 'write-lyrics', 'write-cover'],
            'full': [k.split('.')[-1] for k in self.CATEGORIES['Metadata Tagging'] if 'use-mp4box-artist' not in k]
        }
        
        active_preset = [f"tag-options.{p}" for p in presets.get(preset, [])]
        
        for key, widget in self.widgets.items():
            if key.startswith('tag-options.') and isinstance(widget, QCheckBox):
                widget.setChecked(key in active_preset)
        
        self._mark_dirty()

    def _copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied '{text}' to clipboard", 2000)

    def statusBar(self):
        return self.parent().window().statusBar()

    def _show_info_popup(self, title: str, body: str):
        popup = InfoPopup(title, body, self)
        popup.exec()

    def _browse_dir_into(self, line: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", os.getcwd())
        if path: line.setText(path)

    def _show_storefront_detect_warning(self, line: QLineEdit, btn: QPushButton):
        title = "Storefront Detection Notice"
        body = ("This feature determines your storefront code (e.g., 'us') from your current IP address. "
                "If you are using a VPN, the detected code will reflect the VPN's location.<br><br>"
                "This setting <b>must</b> match your Apple account's registered country. "
                "If the auto-detected value is different, please correct it manually to prevent errors.")
        
        popup = InfoPopup(title, body, self)
        if popup.exec() == QDialog.DialogCode.Accepted:
            self._detect_storefront(line, btn)

    def _detect_storefront(self, line: QLineEdit, btn: QPushButton):
        btn.setEnabled(False); btn.setText("…")
        worker = StorefrontDetector()
        worker.signals.finished.connect(lambda sf: self._on_storefront_detected(sf, line, btn))
        worker.signals.error.connect(lambda err: self._on_storefront_error(err, btn))
        self.thread_pool.start(worker)

    def _on_storefront_detected(self, sf: str, line: QLineEdit, btn: QPushButton):
        line.setText(sf)
        btn.setEnabled(True); btn.setText("Detect")

    def _on_storefront_error(self, err: str, btn: QPushButton):
        QMessageBox.warning(self, "Detection failed", err)
        btn.setEnabled(True); btn.setText("Detect")

    def _mark_dirty(self, *args):
        self._dirty = True

    def _collect(self) -> Dict[str, Any]:
        out = copy.deepcopy(self.config)
        for key, w in self.widgets.items():
            value = None
            if isinstance(w, QComboBox):
                val = w.currentText()
                if w.property("coerce_int"):
                    try: val = int(val)
                    except Exception: pass
                value = val
            elif isinstance(w, QLineEdit):
                v = w.text()
                default_val = self._get_default_value(key)
                if isinstance(default_val, int):
                    try: value = int(v)
                    except Exception: value = 0
                else: value = v
            elif isinstance(w, QCheckBox):
                value = w.isChecked()

            if '.' in key:
                parent_key, child_key = key.split('.')
                if parent_key not in out:
                    out[parent_key] = {}
                out[parent_key][child_key] = value
            else:
                out[key] = value
        return out

    def _write(self, data: Dict[str, Any]):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not write config: {e}")

    def _on_back(self):
        if self._dirty and not self._confirm_discard(): return
        self.back_requested.emit()

    def _confirm_discard(self) -> bool:
        r = QMessageBox.question(self, "Discard changes?", "You have unsaved changes. Are you sure you want to discard them?")
        return r == QMessageBox.StandardButton.Yes

    def _update_widgets_from_config(self):
        """Efficiently update widget values from the current config without rebuilding the UI."""
        for key, w in self.widgets.items():
            value = self._get_config_value(key)
            
            if isinstance(w, QComboBox):
                w.setCurrentText(str(value))
            elif isinstance(w, QLineEdit):
                w.setText(str(value or ''))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(value))

    def _on_reset(self):
        reply = QMessageBox.question(self, "Confirm Reset", 
                                     "Do you really want to reset format, quality, and lyric settings to their defaults?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            for key in self.PARTIAL_RESET_KEYS:
                if key in self.config and key in self.DEFAULTS:
                    self.config[key] = copy.deepcopy(self.DEFAULTS[key])


            self._update_widgets_from_config()
            self._dirty = True

            title = "Info"
            body = ("Settings for naming, quality, and lyrics were reset.\n\n"
                    "Your tokens, storefront, language, and save folders have been preserved.")
            self._show_info_popup(title, body)

    def _on_cancel(self):
        if self._dirty and not self._confirm_discard(): return
        self.config = copy.deepcopy(self.original)
        self._populate_panes()
        self._dirty = False
        self.back_requested.emit()

    def _on_apply(self):
        data = self._collect()
        self._write(data)
        self.original = copy.deepcopy(data)
        self.config = copy.deepcopy(data)
        self._dirty = False
        self.settings_applied.emit(data)
        self.statusBar().showMessage("Settings applied.", 2000)

    def _on_save(self):
        self._on_apply()
        self.back_requested.emit()

    def highlight_media_user_token(self):
        key = 'media-user-token'
        token_edit = self.widgets.get(key)
        if not token_edit:
            return

      
        target_index = None
        for btn in self.nav_button_group.buttons():
            if btn.text() == "General":
                target_index = self.nav_button_group.id(btn)
                btn.setChecked(True)
                break
        if target_index is not None:
            self.content_stack.setCurrentIndex(target_index)

        
        sa = self.content_stack.currentWidget()  
        if sa:
            sa.ensureWidgetVisible(token_edit, 20, 20)
        token_edit.setFocus()

        
        token_edit.setProperty("alert", True)
        token_edit.style().unpolish(token_edit)
        token_edit.style().polish(token_edit)

  
        def _clear():
            token_edit.setProperty("alert", False)
            token_edit.style().unpolish(token_edit)
            token_edit.style().polish(token_edit)
        QTimer.singleShot(2400, _clear)
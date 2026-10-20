import os
import subprocess
import sys
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QFileDialog, QSizePolicy, QGraphicsDropShadowEffect, QStackedWidget, QProgressBar,
    QMenu, QApplication, QComboBox, QCheckBox
)
from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot, QThreadPool, QObject, Qt, QFileSystemWatcher, QTimer,
    QPropertyAnimation, QEasingCurve, QPointF, pyqtProperty, QSettings
)
from PyQt6.QtGui import QColor, QPixmap, QPainter, QPen, QPolygonF, QFontMetrics
from .search_widgets import LoadingSpinner, round_pixmap
from .search_cards import SettingsButton
from mutagen import File

try:
    from mutagen.opus import Opus
except ImportError:
    Opus = None

class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._original_text = text
        self.setText(text)
    
    def setText(self, text):
        self._original_text = text
        self._updateElidedText()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateElidedText()
    
    def _updateElidedText(self):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(
            self._original_text, 
            Qt.TextElideMode.ElideRight, 
            self.width()
        )
        super().setText(elided)

class ChevronIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rotation = 0
        self.setFixedSize(12, 12)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def _get_rotation(self):
        return self._rotation

    def setRotation(self, rotation):
        if self._rotation != rotation:
            self._rotation = rotation
            self.update()

    rotation = pyqtProperty(float, fget=_get_rotation, fset=setRotation)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#e0e0e0"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        
        w, h = self.width(), self.height()
        painter.translate(w / 2, h / 2)
        painter.rotate(self._rotation)
        painter.translate(-w / 2, -h / 2)
        
        points = [QPointF(w * 0.25, h * 0.35), QPointF(w * 0.5, h * 0.6), QPointF(w * 0.75, h * 0.35)]
        painter.drawPolyline(QPolygonF(points))

class StickyHeader(QFrame):
    clicked = pyqtSignal()
    download_clicked = pyqtSignal()
    remove_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("StickyHeader")
        
        self.setStyleSheet("""
            #StickyHeader {
                background-color: transparent;
                border: 1px solid #444;
                border-radius: 6px;
                margin: 2px 0;
            }
            #StickyHeader:hover {
                background-color: rgba(255, 255, 255, 0.04);
                border-color: #555;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.chevron = ChevronIcon(self)
        
        self.title_label = ElidedLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; color: #e0e0e0; border: none; background: transparent; font-size: 10pt;")
        
        self.status_tag = QLabel()
        self.status_tag.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.status_tag.setStyleSheet("QLabel { border-radius: 4px; padding: 3px 8px; font-size: 8pt; font-weight: bold; }")
        
        self.download_button = QPushButton()
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setFixedSize(140, 24)
        self.download_button.setStyleSheet("QPushButton { background-color: #c54863; color: white; border: none; border-radius: 4px; padding: 4px 8px; font-weight: bold; font-size: 8pt; } QPushButton:hover { background-color: #b0415a; }")
        self.download_button.clicked.connect(self.download_clicked.emit)
        self.download_button.hide()

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #aaa; font-size: 8pt; margin-left: 5px;")
        self.progress_label.hide()

        layout.addWidget(self.chevron)
        layout.addWidget(self.title_label, 1)  
        layout.addWidget(self.progress_label)  
        layout.addWidget(self.download_button)  
        layout.addWidget(self.status_tag)  
        
        self.setFixedHeight(42)
        self._is_expanded = False

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        remove_action = menu.addAction("Remove from queue")
        open_folder_action = menu.addAction("Open Folder")
        
        action = menu.exec(self.mapToGlobal(event.pos()))
        
        if action == remove_action:
            self.remove_requested.emit()
        elif action == open_folder_action:
            self.open_folder_requested.emit()

    def set_expanded(self, expanded, animate=True):
        self._is_expanded = expanded
        if animate:
            self.chevron_anim = QPropertyAnimation(self.chevron, b"rotation", self)
            self.chevron_anim.setDuration(250)
            self.chevron_anim.setStartValue(self.chevron.rotation)
            self.chevron_anim.setEndValue(180 if expanded else 0)
            self.chevron_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.chevron_anim.start()
        else:
            self.chevron.setRotation(180 if expanded else 0)

    def update_status_tag(self, found, total):
        if total == 0:
            self.status_tag.hide()
            return
            
        if found == total:
            self.status_tag.setText("All Lyrics Found")
            self.status_tag.setStyleSheet("background-color: #2E7D32; color: white; border-radius: 4px; padding: 3px 8px; font-size: 8pt; font-weight: bold;")
        elif found > 0:
            self.status_tag.setText(f"Lyrics: {found}/{total}")
            self.status_tag.setStyleSheet("background-color: #555; color: #ddd; border-radius: 4px; padding: 3px 8px; font-size: 8pt; font-weight: bold;")
        else:
            self.status_tag.setText("No Lyrics Found")
            self.status_tag.setStyleSheet("background-color: #444; color: #aaa; border-radius: 4px; padding: 3px 8px; font-size: 8pt; font-weight: bold;")
        self.status_tag.show()

    def update_download_action(self, missing_count):
        if missing_count > 0:
            self.download_button.setText(f"Download Missing ({missing_count})")
            self.download_button.show()
            self.download_button.setEnabled(True)
        else:
            self.download_button.hide()
            self.progress_label.hide()

    def set_downloading_state(self, is_downloading):
        if is_downloading:
            self.download_button.setEnabled(False)
            self.download_button.setText("Downloading...")
            self.progress_label.setText("")
            self.progress_label.show()
        else:
            self.download_button.setEnabled(True)
            self.progress_label.hide()

    def update_progress_text(self, text):
        self.progress_label.setText(text)

    def mousePressEvent(self, event):
        is_on_button = self.download_button.isVisible() and self.download_button.geometry().contains(event.pos())
        if not is_on_button:
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
        super().mousePressEvent(event)

class LocalTrackCard(QFrame):
    get_lyrics_requested = pyqtSignal(str)
    HEIGHT = 50

    def __init__(self, track_info, parent=None):
        super().__init__(parent)
        self.track_info = track_info
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("LocalTrackCard")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(15)

        self.artwork_label = QLabel()
        self.artwork_label.setObjectName("LyricsArtwork")
        self.artwork_label.setFixedSize(34, 34)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.artwork_label)

        self.title_label = QLabel(self.track_info.get('title', 'Unknown Title'))
        self.title_label.setObjectName("LyricsTitle")
        self.artist_label = QLabel(self.track_info.get('artist', 'Unknown Artist'))
        self.artist_label.setObjectName("LyricsArtist")

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.artist_label)
        main_layout.addLayout(info_layout, 1)

        self.action_button = QPushButton()
        self.action_button.setObjectName("LyricsAction")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.setFixedSize(85, 26)
        self.action_button.clicked.connect(self._on_action)
        main_layout.addWidget(self.action_button)

        self._set_artwork()
        self.update_status(self.track_info.get('has_lyrics', False), self.track_info.get('message'))

    def _set_artwork(self):
        image = self.track_info.get('artwork')
        if image is not None and not image.isNull():
            pixmap = QPixmap.fromImage(image).scaled(
                self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.artwork_label.setPixmap(round_pixmap(pixmap, 4))
        else:
            self.artwork_label.setText((self.track_info.get('title') or '?')[0].upper())

    def update_status(self, has_lyrics, message=None):
        self.track_info['has_lyrics'] = has_lyrics
        lowered = (message or "").lower()
        if lowered in ("queued", "downloading..."):
            state, enabled = "busy", False
        elif lowered == "failed":
            state, enabled = "failed", True
        elif lowered == "not available":
            state, enabled = "unavailable", False
        elif has_lyrics:
            state, enabled = "view", lowered != "exists"
        else:
            state, enabled = "get", True
        self.action_button.setText(message or ("View" if has_lyrics else "Get Lyrics"))
        self.action_button.setEnabled(enabled)
        if self.action_button.property("state") != state:
            self.action_button.setProperty("state", state)
            self.action_button.style().unpolish(self.action_button)
            self.action_button.style().polish(self.action_button)

    def _on_action(self):
        if self.track_info.get('has_lyrics'):
            self._view_lyrics()
        else:
            self.get_lyrics_requested.emit(self.track_info['filepath'])

    def _view_lyrics(self):
        base, _ = os.path.splitext(self.track_info.get('filepath'))
        lyrics_file = next((f for f in [base + '.lrc', base + '.ttml', base + '.txt'] if os.path.exists(f)), None)
        if lyrics_file:
            try:
                if sys.platform == "win32":
                    os.startfile(lyrics_file)
                else:
                    subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", lyrics_file])
            except Exception as e:
                print(f"Error opening lyrics file: {e}")

class LyricsDownloaderPage(QWidget):
    menu_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.tracks = {}
        self.sections = {}
        self.card_widgets = {}
        self.scanned_data = {}
        self.current_path = None
        self.total_files_to_scan = 0
        self.processed_files = 0
        self.missing_lyrics_count = 0
        self.setObjectName("LyricsDownloaderPage")

        self._queue = deque()
        self._queued = set()
        self._inflight = set()
        self._max_concurrent = 4
        self._run_total = 0
        self._run_done = 0
        self._build_jobs = deque()
        self._build_timer = QTimer(self)
        self._build_timer.setInterval(0)
        self._build_timer.timeout.connect(self._build_next_batch)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        hero = QFrame()
        hero.setObjectName("HeroFrame")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        
        self.menu_btn = SettingsButton(hero)
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        hero_layout.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        title_box = QVBoxLayout()
        title_box.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)  
        
        title_label = QLabel("Your Music, Now with Lyrics")  
        title_label.setObjectName("SettingsTitle")
        subtitle_label = QLabel("Scan your music folder to find and download synced lyrics for all your tracks.")
        subtitle_label.setObjectName("SettingsSubtitle")
        
        for label in (title_label, subtitle_label):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(0, 0, 0, 180))
            shadow.setOffset(0, 1)
            label.setGraphicsEffect(shadow)
            
        title_box.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)  
        title_box.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)  
        hero_layout.addLayout(title_box, 1)
        root_layout.addWidget(hero)
        
        content_frame = QFrame()
        content_frame.setStyleSheet("background-color: #1f1f1f;")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        
        controls_layout = QHBoxLayout()
        
        self.folder_button = QPushButton("Open Music Folder...")
        self.folder_button.clicked.connect(self.scan_local_folder)
        self.folder_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.folder_button.setStyleSheet("""
            QPushButton {
                background-color: #d60117; 
                border: none;
                border-radius: 6px; 
                padding: 6px 14px; 
                color: white;
                font-weight: bold;
            }
            QPushButton:hover { 
                background-color: #b80114;
            }
        """)
        
        self.download_all_button = QPushButton("Download All Missing")
        self.download_all_button.clicked.connect(self._on_download_all_clicked)
        self.download_all_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.download_all_button.setStyleSheet("""
            QPushButton { 
                background-color: #c54863; 
                color: white; 
                border: none; 
                border-radius: 4px; 
                padding: 6px 12px; 
                font-weight: bold; 
            } 
            QPushButton:hover { 
                background-color: #b0415a; 
            }
        """)
        self.download_all_button.hide()
        
        self.directory_label = QLabel("No folder selected.")
        self.directory_label.setStyleSheet("color: #888; font-style: italic; margin-left: 10px; font-size: 10pt;")
        
        controls_layout.addWidget(self.folder_button)
        controls_layout.addWidget(self.download_all_button)
        controls_layout.addStretch(1)
        content_layout.addLayout(controls_layout)
        content_layout.addLayout(self._create_options_row())
        
        self.global_progress_bar = QProgressBar()
        self.global_progress_bar.setFixedHeight(4)
        self.global_progress_bar.setTextVisible(False)
        self.global_progress_bar.setStyleSheet("QProgressBar { border: none; border-radius: 2px; background-color: #444; margin-top: 8px; } QProgressBar::chunk { background-color: #c54863; border-radius: 2px; }")
        self.global_progress_bar.hide()
        content_layout.addWidget(self.global_progress_bar)

        self.right_click_info_label = QLabel("Right-click on a folder for more options.")
        self.right_click_info_label.setStyleSheet("color: #888; font-size: 8pt; font-style: italic; margin-top: 8px;")
        self.right_click_info_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.right_click_info_label.hide()
        content_layout.addWidget(self.right_click_info_label)

        self.main_stack = QStackedWidget()
        content_layout.addWidget(self.main_stack, 1)
        
        self.placeholder_widget = self._create_placeholder_widget()
        self.main_stack.addWidget(self.placeholder_widget)
        
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.setSpacing(15)
        
        spinner_status_layout = QHBoxLayout()
        spinner_status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner_status_layout.setSpacing(15)
        
        self.loading_spinner = LoadingSpinner(self)
        self.loading_spinner.setFixedSize(50, 50)
        
        self.loading_status_label = QLabel("Scanning...")
        self.loading_status_label.setStyleSheet("font-size: 12pt; color: #ccc; background: transparent;")
        
        spinner_status_layout.addWidget(self.loading_spinner)
        spinner_status_layout.addWidget(self.loading_status_label)
        loading_layout.addLayout(spinner_status_layout)
        self.main_stack.addWidget(self.loading_widget)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none; background-color: transparent;")
        
        self.results_container = QWidget()
        self.results_container.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(2)
        self.results_layout.setContentsMargins(0, 10, 0, 20)
        
        self.scroll_area.setWidget(self.results_container)
        self.main_stack.addWidget(self.scroll_area)
        
        root_layout.addWidget(content_frame, 1)
        self.main_stack.setCurrentWidget(self.placeholder_widget)
        
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher_reset_timer = QTimer(self)
        self._watcher_reset_timer.setSingleShot(True)
        self._watcher_debounce_timer = QTimer(self)
        self._watcher_debounce_timer.setSingleShot(True)
        self._watcher_debounce_timer.setInterval(500)
        self._watcher_debounce_timer.timeout.connect(self._perform_rescan)
        
        self.setStyleSheet("""
            QWidget#LyricsDownloaderPage { 
                background-color: #1f1f1f; 
                color: #e0e0e0; 
            }
            QFrame#HeroFrame { 
                background-color: #2a2a2a; 
                border-bottom: 1px solid #3a3a3a; 
            }
            QLabel#SettingsTitle { 
                font-size: 22pt; 
                font-weight: 800; 
                color: white; 
                background: transparent; 
            }
            QLabel#SettingsSubtitle {
                font-size: 9.5pt;
                color: #b0b0b0;
                font-weight: normal;
                background: transparent;
            }
            #LocalTrackCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2c2c2c, stop:1 #2a2a2a);
                border: none; border-bottom: 1px solid #444; margin: 0; padding: 0;
            }
            #LocalTrackCard:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a3a3a, stop:1 #333);
            }
            #LocalTrackCard QLabel { background-color: transparent; border: none; }
            QLabel#LyricsArtwork {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3a3a3a, stop:1 #333);
                border-radius: 4px; color: #999; border: 1px solid #444; font-size: 14pt; font-weight: bold;
            }
            QLabel#LyricsTitle { font-weight: bold; font-size: 10pt; color: #e0e0e0; }
            QLabel#LyricsArtist { color: #bbb; font-size: 8pt; }
            QPushButton#LyricsAction {
                color: white; border: none; border-radius: 4px; padding: 3px 6px;
                font-weight: bold; font-size: 8pt; background-color: #c54863;
            }
            QPushButton#LyricsAction:hover { background-color: #b0415a; }
            QPushButton#LyricsAction[state="view"] { background-color: #4CAF50; }
            QPushButton#LyricsAction[state="view"]:hover { background-color: #45a049; }
            QPushButton#LyricsAction[state="busy"] { background-color: #8a3a4c; color: #e8e8e8; }
            QPushButton#LyricsAction[state="failed"] { background-color: #f44336; }
            QPushButton#LyricsAction[state="unavailable"] { background-color: #555; color: #ccc; }
        """)

    def _create_options_row(self):
        self.options_store = QSettings("apmyx", "lyrics-downloader")
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(8)

        def combo(label, key, items, default):
            caption = QLabel(label)
            caption.setStyleSheet("color: #aaa; font-size: 9pt;")
            box = QComboBox()
            for text, value in items:
                box.addItem(text, value)
            index = box.findData(self.options_store.value(key, default))
            box.setCurrentIndex(index if index >= 0 else 0)
            box.currentIndexChanged.connect(lambda _: self._save_options())
            row.addWidget(caption)
            row.addWidget(box)
            row.addSpacing(8)
            return box

        self.timing_box = combo("Timing", "timing", [("Line", "line"), ("Syllable / word", "syllable")], "line")
        self.format_box = combo("Format", "format", [("LRC", "lrc"), ("TTML", "ttml"), ("Plain text", "text")], "lrc")
        self.translation_check = QCheckBox("Translation")
        self.pronunciation_check = QCheckBox("Pronunciation")
        for check, key in ((self.translation_check, "translation"), (self.pronunciation_check, "pronunciation")):
            check.setChecked(str(self.options_store.value(key, "true")).lower() == "true")
            check.setToolTip("Adds extra LRC lines when Apple provides them.")
            check.toggled.connect(lambda _: self._save_options())
            row.addWidget(check)
        row.addStretch(1)
        self._sync_option_states()
        return row

    def _sync_option_states(self):
        output = self.format_box.currentData()
        self.timing_box.setEnabled(output != "text")
        for check in (self.translation_check, self.pronunciation_check):
            check.setEnabled(output == "lrc")

    def _save_options(self):
        self._sync_option_states()
        options = self.lyrics_options()
        for key in ("timing", "format"):
            self.options_store.setValue(key, options[key])
        self.options_store.setValue("translation", "true" if self.translation_check.isChecked() else "false")
        self.options_store.setValue("pronunciation", "true" if self.pronunciation_check.isChecked() else "false")

    def lyrics_options(self):
        extras = [kind for kind, check in (("translation", self.translation_check), ("pronunciation", self.pronunciation_check)) if check.isChecked()]
        return {"timing": self.timing_box.currentData(), "format": self.format_box.currentData(), "extras": extras}

    def _create_placeholder_widget(self):
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(25)

        subtitle_label = QLabel("Find synced lyrics for your local music library.")
        subtitle_label.setStyleSheet("font-size: 14pt; color: #aaa;")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(20)

        info_title = QLabel("How It Works")
        info_title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #e0e0e0; border-bottom: 1px solid #444; padding-bottom: 8px; margin-bottom: 10px;")
        info_layout.addWidget(info_title, 0, Qt.AlignmentFlag.AlignHCenter)

        def create_info_point(icon, text):
            point_widget = QWidget()
            point_layout = QHBoxLayout(point_widget)
            point_layout.setSpacing(15)
            point_layout.setContentsMargins(0, 0, 0, 0)
            icon_label = QLabel(icon)
            icon_label.setFixedWidth(20)
            icon_label.setStyleSheet("font-size: 16pt; color: #c54863;")
            text_label = QLabel(text)
            text_label.setWordWrap(True)
            text_label.setStyleSheet("font-size: 11pt; color: #ccc; line-height: 1.5;")
            point_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
            point_layout.addWidget(text_label, 1)
            return point_widget

        info_layout.addWidget(create_info_point("ⓘ", "<b>Lyrics Source:</b> Lyrics come from your configured <b>wrapper</b> (no token needed), or from Apple Music with a <b>Media User Token</b> set in Settings."))
        info_layout.addWidget(create_info_point("✔", "<b>File Format:</b> Choose <b>LRC</b> (line or syllable timing), <b>TTML</b>, or <b>plain text</b>. Files are saved next to your songs."))
        info_layout.addWidget(create_info_point("!", "<b>Matching Process:</b> Songs are identified using their <b>Title</b>, <b>Artist</b>, and <b>Album</b> metadata. Files with missing or incorrect tags cannot be matched and will be skipped."))

        content_row_layout = QHBoxLayout()
        content_row_layout.addStretch(1)
        content_row_layout.addLayout(info_layout, 2)
        content_row_layout.addStretch(1)

        main_layout.addStretch(1)
        main_layout.addWidget(subtitle_label)
        main_layout.addLayout(content_row_layout)
        main_layout.addStretch(2)
        
        return widget

    def scan_local_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Music Folder", self.current_path or os.path.expanduser("~"))
        if path:
            self._start_scan(path)

    def _start_scan(self, path):
        if self.current_path:
            self.file_watcher.removePath(self.current_path)
        self.current_path = path
        self.directory_label.setText(f"Scanning: {path}")
        self._clear_results()
        self.main_stack.setCurrentWidget(self.loading_widget)
        self.loading_status_label.setText("Finding audio files...")
        self.loading_spinner.start()
        self.download_all_button.hide()
        self.right_click_info_label.hide()
        self.controller.scan_local_directory(path)
        self.file_watcher.addPath(path)

    @pyqtSlot(dict)
    def on_scan_results(self, result):
        if result['type'] == 'scan_started':
            self.total_files_to_scan = result['data']['total_files']
        elif result['type'] == 'chunk':
            self.processed_files += len(result['data'])
            self.loading_status_label.setText(f"Processing {self.processed_files}/{self.total_files_to_scan} files...")
            for track in result['data']:
                track['message'] = None
                self.scanned_data.setdefault(os.path.dirname(track['filepath']), []).append(track)
        elif result['type'] == 'complete':
            self._build_ui_from_scan_data()
        elif result['type'] == 'error':
            self.loading_spinner.stop()
            self.directory_label.setText(f"Error: {result['data']}")

    def _build_ui_from_scan_data(self):
        self.loading_spinner.stop()
        self.main_stack.setCurrentWidget(self.scroll_area)
        self.directory_label.setText(f"Current Folder: {self.current_path}")
        self.results_container.setUpdatesEnabled(False)
        if self.scanned_data:
            self.right_click_info_label.show()

        for dir_path in sorted(self.scanned_data):
            tracks = self.scanned_data[dir_path]
            header = StickyHeader(self._get_display_path(dir_path))
            self.results_layout.addWidget(header)

            container = QWidget()
            container.setStyleSheet("background: transparent; border: none;")
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(15, 0, 15, 0)
            container_layout.setSpacing(0)
            container.setMaximumHeight(0)
            self.results_layout.addWidget(container)

            found_count = sum(1 for t in tracks if t['has_lyrics'])
            missing_count = len(tracks) - found_count
            self.missing_lyrics_count += missing_count
            for track in tracks:
                self.tracks[track['filepath']] = track
            self.sections[dir_path] = {
                'header': header, 'container': container, 'layout': container_layout,
                'filepaths': [t['filepath'] for t in tracks], 'built': 0, 'is_expanded': False,
                'missing_count': missing_count, 'found_count': found_count, 'total_count': len(tracks),
                'queued_total': 0, 'queued_done': 0,
            }
            header.update_status_tag(found_count, len(tracks))
            header.update_download_action(missing_count)
            header.clicked.connect(lambda d=dir_path: self._toggle_section(d))
            header.download_clicked.connect(lambda d=dir_path: self._on_download_all_section(d))
            header.remove_requested.connect(lambda d=dir_path: self._remove_section(d))
            header.open_folder_requested.connect(lambda d=dir_path: self._open_directory(d))

        self.results_container.setUpdatesEnabled(True)
        self.update_download_all_button()

    def _get_display_path(self, dir_path):
        if self.current_path and dir_path.startswith(self.current_path):
            rel_path = os.path.relpath(dir_path, self.current_path)
            return rel_path if rel_path != '.' else f"{os.path.basename(self.current_path)} [Root]"
        return dir_path

    def _toggle_section(self, dir_path):
        info = self.sections.get(dir_path)
        if not info:
            return
        container = info['container']
        is_expanding = not info['is_expanded']
        info['is_expanded'] = is_expanding
        info['header'].set_expanded(is_expanding)
        if is_expanding and info['built'] < len(info['filepaths']) and dir_path not in self._build_jobs:
            self._build_jobs.append(dir_path)
            self._build_timer.start()

        if not hasattr(container, 'animation'):
            container.animation = QPropertyAnimation(container, b"maximumHeight")
            container.animation.setDuration(300)
            container.animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        container.animation.stop()
        container.animation.setStartValue(container.maximumHeight())
        container.animation.setEndValue(len(info['filepaths']) * LocalTrackCard.HEIGHT if is_expanding else 0)
        container.animation.start()

    def _build_next_batch(self):
        remaining = 40
        while self._build_jobs and remaining:
            dir_path = self._build_jobs[0]
            info = self.sections.get(dir_path)
            if not info or info['built'] >= len(info['filepaths']):
                self._build_jobs.popleft()
                continue
            info['container'].setUpdatesEnabled(False)
            while info['built'] < len(info['filepaths']) and remaining:
                filepath = info['filepaths'][info['built']]
                info['built'] += 1
                remaining -= 1
                track = self.tracks.get(filepath)
                if track is None:
                    continue
                card = LocalTrackCard(track)
                card.get_lyrics_requested.connect(self._on_get_lyrics_requested)
                info['layout'].addWidget(card)
                self.card_widgets[filepath] = card
            info['container'].setUpdatesEnabled(True)
        if not self._build_jobs:
            self._build_timer.stop()

    def update_download_all_button(self):
        text = f"Download All Missing ({self.missing_lyrics_count})" if self.missing_lyrics_count > 0 else ""
        self.download_all_button.setText(text)
        self.download_all_button.setVisible(bool(self.missing_lyrics_count))

    def _busy(self):
        return bool(self._queue or self._inflight)

    def _set_track_message(self, filepath, message):
        track = self.tracks.get(filepath)
        if track is None:
            return
        track['message'] = message
        card = self.card_widgets.get(filepath)
        if card is not None:
            card.update_status(track['has_lyrics'], message)

    def _enqueue(self, filepaths, front=False):
        added = []
        for filepath in filepaths:
            track = self.tracks.get(filepath)
            if track is None or track['has_lyrics'] or filepath in self._queued or filepath in self._inflight:
                continue
            added.append(filepath)
        if not added:
            return
        self._watcher_reset_timer.stop()
        if front:
            self._queue.extendleft(reversed(added))
        else:
            self._queue.extend(added)
        self._queued.update(added)
        for filepath in added:
            self._set_track_message(filepath, "Queued")
            info = self.sections.get(os.path.dirname(filepath))
            if info:
                info['queued_total'] += 1
                self._update_section_progress(info)
        self._run_total += len(added)
        self.global_progress_bar.setMaximum(self._run_total)
        self.global_progress_bar.setValue(self._run_done)
        self.global_progress_bar.show()
        self._pump_queue()

    def _pump_queue(self):
        while self._queue and len(self._inflight) < self._max_concurrent:
            filepath = self._queue.popleft()
            self._queued.discard(filepath)
            track = self.tracks.get(filepath)
            if track is None:
                continue
            self._inflight.add(filepath)
            self._set_track_message(filepath, "Downloading...")
            request = {key: track.get(key) for key in ('filepath', 'title', 'artist', 'album')}
            request['options'] = self.lyrics_options()
            self.controller.download_lyrics_for_track(request, filepath)

    def _update_section_progress(self, info):
        header = info['header']
        if info['queued_done'] < info['queued_total']:
            header.set_downloading_state(True)
            header.update_progress_text(f"{info['queued_done']}/{info['queued_total']}")
        else:
            info['queued_total'] = info['queued_done'] = 0
            header.set_downloading_state(False)
            header.update_download_action(info['missing_count'])

    @pyqtSlot(str)
    def _on_get_lyrics_requested(self, filepath):
        self._enqueue([filepath], front=True)

    def _on_download_all_clicked(self):
        self._enqueue([fp for fp, track in self.tracks.items() if not track['has_lyrics']])

    def _on_download_all_section(self, dir_path):
        info = self.sections.get(dir_path)
        if info:
            self._enqueue([fp for fp in info['filepaths'] if fp in self.tracks and not self.tracks[fp]['has_lyrics']])

    @pyqtSlot(str, bool, str)
    def on_lyrics_download_finished(self, filepath, success, message):
        counted = filepath in self._inflight
        self._inflight.discard(filepath)
        track = self.tracks.get(filepath)
        info = self.sections.get(os.path.dirname(filepath))
        if track is not None:
            if success and not track['has_lyrics'] and info:
                self.missing_lyrics_count = max(0, self.missing_lyrics_count - 1)
                info['missing_count'] = max(0, info['missing_count'] - 1)
                info['found_count'] += 1
                info['header'].update_status_tag(info['found_count'], info['total_count'])
            track['has_lyrics'] = track['has_lyrics'] or success
            self._set_track_message(filepath, message.title())
        if counted:
            self._run_done += 1
            self.global_progress_bar.setValue(self._run_done)
            if info:
                info['queued_done'] += 1
                self._update_section_progress(info)
        self.update_download_all_button()
        self._pump_queue()
        if not self._busy():
            self._run_total = self._run_done = 0
            QTimer.singleShot(1000, self._hide_progress_if_idle)
            self._watcher_reset_timer.start(2000)

    def _hide_progress_if_idle(self):
        if not self._busy():
            self.global_progress_bar.hide()

    def _clear_results(self):
        self._build_timer.stop()
        self._build_jobs.clear()
        for info in self.sections.values():
            if hasattr(info['container'], 'animation'):
                info['container'].animation.stop()
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self.tracks.clear()
        self.sections.clear()
        self.card_widgets.clear()
        self.scanned_data.clear()
        self._queue.clear()
        self._queued.clear()
        self._inflight.clear()
        self._run_total = self._run_done = 0
        self.processed_files = self.total_files_to_scan = self.missing_lyrics_count = 0
        self.global_progress_bar.hide()
        self.right_click_info_label.hide()

    def _on_directory_changed(self, path):
        if path == self.current_path and not self._busy() and not self._watcher_reset_timer.isActive():
            self._watcher_debounce_timer.start()

    def _perform_rescan(self):
        if self.current_path and not self._busy():
            self._start_scan(self.current_path)

    def _open_directory(self, path):
        if not os.path.isdir(path):
            print(f"Directory does not exist: {path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path], check=True)
        except Exception as e:
            print(f"Error opening directory {path}: {e}")

    def _remove_section(self, dir_path):
        info = self.sections.pop(dir_path, None)
        if not info:
            return
        removed = set(info['filepaths'])
        pending = [fp for fp in self._queue if fp in removed]
        if pending:
            self._queue = deque(fp for fp in self._queue if fp not in removed)
            self._queued.difference_update(pending)
            self._run_total = max(self._run_done, self._run_total - len(pending))
            self.global_progress_bar.setMaximum(max(1, self._run_total))
        for filepath in removed:
            self.tracks.pop(filepath, None)
            self.card_widgets.pop(filepath, None)
        self.scanned_data.pop(dir_path, None)
        self.missing_lyrics_count = max(0, self.missing_lyrics_count - info['missing_count'])
        self.update_download_all_button()
        info['container'].deleteLater()
        info['header'].deleteLater()
        if not self._busy():
            self.global_progress_bar.hide()
        if not self.sections:
            self.main_stack.setCurrentWidget(self.placeholder_widget)
            self.right_click_info_label.hide()

import os
import subprocess
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QFileDialog, QSizePolicy, QGraphicsDropShadowEffect, QStackedWidget, QProgressBar,
    QMenu, QApplication
)
from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot, QThreadPool, QObject, Qt, QFileSystemWatcher, QTimer,
    QPropertyAnimation, QEasingCurve, QPointF, pyqtProperty
)
from PyQt6.QtGui import QColor, QPixmap, QFont, QPainter, QPen, QPolygonF, QFontMetrics
from .search_widgets import LoadingSpinner, round_pixmap
from .search_cards import SettingsButton
from mutagen import File, MutagenError
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

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
        
        # Use ElidedLabel to prevent overflow
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

        # Fixed layout - title gets stretch, right elements stay fixed
        layout.addWidget(self.chevron)
        layout.addWidget(self.title_label, 1)  # Only this expands
        layout.addWidget(self.progress_label)  # Fixed
        layout.addWidget(self.download_button)  # Fixed
        layout.addWidget(self.status_tag)  # Fixed
        
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
    get_lyrics_requested = pyqtSignal(dict)

    def __init__(self, track_info, parent=None):
        super().__init__(parent)
        self.track_info = track_info
        self.setFixedHeight(50)
        self.setObjectName("LocalTrackCard")
        self.setStyleSheet("""
            #LocalTrackCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2c2c2c, stop:1 #2a2a2a);
                border: none; border-bottom: 1px solid #444; margin: 0; padding: 0;
            }
            #LocalTrackCard:hover { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a3a3a, stop:1 #333); 
            }
            QLabel { background-color: transparent; }
        """)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(15)
        
        self.artwork_label = QLabel("...")
        self.artwork_label.setFixedSize(34, 34)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3a3a3a, stop:1 #333); border-radius: 4px; color: #999; border: 1px solid #444;")
        self.artwork_label.setFont(QFont("Inter Tight", 14, QFont.Weight.Bold))
        main_layout.addWidget(self.artwork_label)
        
        self.title_label = QLabel(self.track_info.get('title', 'Unknown Title'))
        self.title_label.setStyleSheet("font-weight: bold; font-size: 10pt; color: #e0e0e0; border: none;")
        
        self.artist_label = QLabel(self.track_info.get('artist', 'Unknown Artist'))
        self.artist_label.setStyleSheet("color: #bbb; font-size: 8pt; border: none;")
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.artist_label)
        main_layout.addLayout(info_layout, 1)
        
        self.action_button = QPushButton()
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.setFixedSize(85, 26)
        main_layout.addWidget(self.action_button)
        
        self._set_artwork()
        self.update_status(self.track_info.get('has_lyrics', False))

    def _set_artwork(self):
        artwork_data = self.track_info.get('artwork_data')
        if artwork_data:
            pixmap = QPixmap()
            pixmap.loadFromData(artwork_data)
            self.artwork_label.setPixmap(round_pixmap(pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation), 4))
        else:
            self.artwork_label.setText(self.track_info.get('title', '?')[0].upper())

    def update_status(self, has_lyrics, message=None):
        self.track_info['has_lyrics'] = has_lyrics
        self.action_button.setEnabled(True)
        self.action_button.setText(message or ("View" if has_lyrics else "Get Lyrics"))
        
        try:
            self.action_button.clicked.disconnect()
        except TypeError:
            pass

        if has_lyrics:
            self.action_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 4px; padding: 3px 6px; font-weight: bold; font-size: 8pt; } QPushButton:hover { background-color: #45a049; }")
            self.action_button.clicked.connect(self._view_lyrics)
        else:
            self.action_button.setStyleSheet("QPushButton { background-color: #c54863; color: white; border: none; border-radius: 4px; padding: 3px 6px; font-weight: bold; font-size: 8pt; } QPushButton:hover { background-color: #b0415a; }")
            self.action_button.clicked.connect(self._get_lyrics)

        if message:
            msg_lower = message.lower()
            if msg_lower in ["downloading...", "exists"]:
                self.action_button.setEnabled(False)
            if msg_lower == "failed":
                self.action_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; border: none; border-radius: 4px; padding: 3px 6px; font-weight: bold; font-size: 8pt; }")
            elif msg_lower == "not available":
                self.action_button.setStyleSheet("QPushButton { background-color: #555; color: #ccc; border: none; border-radius: 4px; padding: 3px 6px; font-weight: bold; font-size: 8pt; }")
                self.action_button.setEnabled(False)

    def _get_lyrics(self):
        self.update_status(False, "Downloading...")
        self.get_lyrics_requested.emit(self.track_info)
        
    def _view_lyrics(self):
        base, _ = os.path.splitext(self.track_info.get('filepath'))
        lyrics_file = next((f for f in [base + '.lrc', base + '.ttml'] if os.path.exists(f)), None)
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
        self.card_widgets = {}
        self.directory_widgets = {}
        self.scanned_data = {}
        self.current_path = None
        self.total_files_to_scan = 0
        self.processed_files = 0
        self.missing_lyrics_count = 0
        self._ignore_watcher = False
        self.download_progress = {}
        self.global_download_progress = {}
        self.setObjectName("LyricsDownloaderPage")
        
        self._pending_cards = []
        self._inflight = 0
        self._max_concurrent = 4
        
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        # Hero section with left-aligned text
        hero = QFrame()
        hero.setObjectName("HeroFrame")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        
        self.menu_btn = SettingsButton(hero)
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        hero_layout.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        title_box = QVBoxLayout()
        title_box.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)  # Left aligned
        
        title_label = QLabel("Your Music, Now with Lyrics")  # Better title
        title_label.setObjectName("SettingsTitle")
        subtitle_label = QLabel("Scan your music folder to find and download synced lyrics for all your tracks.")
        subtitle_label.setObjectName("SettingsSubtitle")
        
        for label in (title_label, subtitle_label):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(0, 0, 0, 180))
            shadow.setOffset(0, 1)
            label.setGraphicsEffect(shadow)
            
        title_box.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)  # Left aligned
        title_box.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)  # Left aligned
        hero_layout.addLayout(title_box, 1)
        root_layout.addWidget(hero)
        
        # Content frame
        content_frame = QFrame()
        content_frame.setStyleSheet("background-color: #1f1f1f;")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        
        # Controls
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
        
        # Progress bar
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

        # Main stack
        self.main_stack = QStackedWidget()
        content_layout.addWidget(self.main_stack, 1)
        
        # Placeholder
        self.placeholder_widget = self._create_placeholder_widget()
        self.main_stack.addWidget(self.placeholder_widget)
        
        # Loading widget
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
        
        # Results scroll area
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
        
        # File watcher
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher_reset_timer = QTimer(self)
        self._watcher_reset_timer.setSingleShot(True)
        self._watcher_reset_timer.timeout.connect(self._unignore_watcher)
        self._watcher_debounce_timer = QTimer(self)
        self._watcher_debounce_timer.setSingleShot(True)
        self._watcher_debounce_timer.setInterval(500)
        self._watcher_debounce_timer.timeout.connect(self._perform_rescan)
        
        # Apply consistent styling with main window background
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
        """)

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

        info_layout.addWidget(create_info_point("ⓘ", "<b>Token Required:</b> A <b>Media User Token</b> must be set in Settings. This is essential for matching your local files with the Apple Music catalog."))
        info_layout.addWidget(create_info_point("✔", "<b>File Format:</b> Found lyrics are saved as standard <b>.lrc</b> files in the same folder as your songs."))
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
                dir_path = os.path.dirname(track['filepath'])
                if dir_path not in self.scanned_data:
                    self.scanned_data[dir_path] = []
                self.scanned_data[dir_path].append(track)
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

        for dir_path in sorted(self.scanned_data.keys()):
            tracks = self.scanned_data[dir_path]
            display_path = self._get_display_path(dir_path)
            
            header = StickyHeader(display_path)
            self.results_layout.addWidget(header)
            
            container = QWidget()
            container.setStyleSheet("background: transparent; border: none;")
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(15, 0, 15, 0)
            container_layout.setSpacing(0)
            self.results_layout.addWidget(container)
            
            cards = [LocalTrackCard(t) for t in tracks]
            found_count = 0
            for card in cards:
                card.get_lyrics_requested.connect(self._on_get_lyrics_requested)
                container_layout.addWidget(card)
                self.card_widgets[card.track_info['filepath']] = card
                if card.track_info['has_lyrics']:
                    found_count += 1
            
            missing_count = len(tracks) - found_count
            self.missing_lyrics_count += missing_count
            
            container.adjustSize()
            full_height = container.sizeHint().height()
            self.directory_widgets[header] = {
                'container': container, 'cards': cards, 'is_expanded': False, 
                'missing_count': missing_count, 'found_count': found_count, 'total_count': len(tracks),
                'full_height': full_height, 'dir_path': dir_path
            }
            
            header.update_status_tag(found_count, len(tracks))
            header.update_download_action(missing_count)
            
            header.clicked.connect(lambda h=header: self._toggle_section(h))
            header.download_clicked.connect(lambda h=header: self._on_download_all_section(h))
            header.remove_requested.connect(lambda h=header: self._remove_section(h))
            header.open_folder_requested.connect(lambda h=header: self._open_section_folder(h))
            
            container.setMaximumHeight(0)

        self.results_container.setUpdatesEnabled(True)
        self.update_download_all_button()

    def _get_display_path(self, dir_path):
        if self.current_path and dir_path.startswith(self.current_path):
            rel_path = os.path.relpath(dir_path, self.current_path)
            return rel_path if rel_path != '.' else f"{os.path.basename(self.current_path)} [Root]"
        return dir_path

    def _toggle_section(self, header):
        info = self.directory_widgets[header]
        container = info['container']
        is_expanding = not info['is_expanded']
        info['is_expanded'] = is_expanding
        header.set_expanded(is_expanding)

        # Smooth animation optimizations
        container.setUpdatesEnabled(False)
        
        if not hasattr(container, 'animation'):
            container.animation = QPropertyAnimation(container, b"maximumHeight")
            container.animation.setDuration(300)
            container.animation.setEasingCurve(QEasingCurve.Type.OutQuart)
            container.animation.finished.connect(lambda: container.setUpdatesEnabled(True))

        # Ensure accurate height calculation
        if is_expanding and not hasattr(info, 'calculated_height'):
            container.adjustSize()
            info['calculated_height'] = container.sizeHint().height()
            info['full_height'] = info['calculated_height']

        container.animation.stop()
        container.animation.setStartValue(container.maximumHeight())
        container.animation.setEndValue(info['full_height'] if is_expanding else 0)
        container.animation.start()

    def update_download_all_button(self):
        text = f"Download All Missing ({self.missing_lyrics_count})" if self.missing_lyrics_count > 0 else ""
        self.download_all_button.setText(text)
        self.download_all_button.setVisible(bool(self.missing_lyrics_count))

    @pyqtSlot(dict)
    def _on_get_lyrics_requested(self, track_info):
        self._ignore_watcher = True
        self.controller.download_lyrics_for_track(track_info, track_info['filepath'])
    
    def _pump_queue(self):
        while self._pending_cards and self._inflight < self._max_concurrent:
            card = self._pending_cards.pop(0)
            self._inflight += 1
            card._get_lyrics()

    def _on_download_all_clicked(self):
        self._ignore_watcher = True
        cards_to_download = [c for c in self.card_widgets.values() if not c.track_info['has_lyrics']]
        if not cards_to_download:
            return

        self.global_download_progress = {'processed': 0, 'total': len(cards_to_download)}
        self.global_progress_bar.setMaximum(len(cards_to_download))
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.show()
        
        self._pending_cards = list(cards_to_download)
        self._pump_queue()
    
    def _on_download_all_section(self, header):
        info = self.directory_widgets.get(header)
        if info:
            self._ignore_watcher = True
            missing_cards = [c for c in info['cards'] if not c.track_info['has_lyrics']]
            if missing_cards:
                header.set_downloading_state(True)
                self.download_progress[header] = {'processed': 0, 'total': len(missing_cards)}
                
                # Add to global queue instead of direct call
                self._pending_cards.extend(missing_cards)
                if not self.global_download_progress:
                    self.global_download_progress = {'processed': 0, 'total': 0}
                    self.global_progress_bar.show()
                
                self.global_download_progress['total'] += len(missing_cards)
                self.global_progress_bar.setMaximum(self.global_download_progress['total'])
                
                self._pump_queue()

    @pyqtSlot(str, bool, str)
    def on_lyrics_download_finished(self, filepath, success, message):
        self._watcher_reset_timer.start(2000)
        if self._inflight > 0:
            self._inflight -= 1
        self._pump_queue()

        if filepath not in self.card_widgets:
            return
        
        card = self.card_widgets[filepath]
        header = next((h for h, i in self.directory_widgets.items() if card in i['cards']), None)
        if not header:
            return

        if self.global_download_progress:
            self.global_download_progress['processed'] += 1
            self.global_progress_bar.setValue(self.global_download_progress['processed'])
            if self.global_download_progress['processed'] >= self.global_download_progress['total']:
                QTimer.singleShot(1000, self.global_progress_bar.hide)
                self.global_download_progress = {}

        info = self.directory_widgets[header]
        if success and not card.track_info['has_lyrics']:
            self.missing_lyrics_count = max(0, self.missing_lyrics_count - 1)
            info['missing_count'] = max(0, info['missing_count'] - 1)
            info['found_count'] += 1
            header.update_download_action(info['missing_count'])
            header.update_status_tag(info['found_count'], info['total_count'])
        
        if header in self.download_progress:
            progress = self.download_progress[header]
            progress['processed'] += 1
            header.update_progress_text(f"{progress['processed']}/{progress['total']}")
            if progress['processed'] >= progress['total']:
                header.set_downloading_state(False)
                header.update_download_action(info['missing_count'])
                del self.download_progress[header]

        self.update_download_all_button()
        card.update_status(success, message.title())

    def _clear_results(self):
        for info in self.directory_widgets.values():
            if hasattr(info['container'], 'animation'):
                info['container'].animation.stop()
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self.card_widgets.clear()
        self.directory_widgets.clear()
        self.scanned_data.clear()
        self.download_progress.clear()
        self.processed_files = self.total_files_to_scan = self.missing_lyrics_count = 0
        self.global_progress_bar.hide()
        self.global_download_progress = {}
        self.right_click_info_label.hide()

    def _on_directory_changed(self, path):
        if not self._ignore_watcher and path == self.current_path:
            self._watcher_debounce_timer.start()
            
    def _perform_rescan(self):
        print("Rescanning folder for changes...")
        self.scan_local_folder()
        
    def _unignore_watcher(self):
        self._ignore_watcher = False

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

    def _open_section_folder(self, header):
        info = self.directory_widgets.get(header)
        if info and 'dir_path' in info:
            self._open_directory(info['dir_path'])

    def _remove_section(self, header):
        info = self.directory_widgets.pop(header, None)
        if not info:
            return

        self.missing_lyrics_count -= info.get('missing_count', 0)
        self.update_download_all_button()

        dir_path = info.get('dir_path')
        if dir_path:
            self.scanned_data.pop(dir_path, None)
        
        for card in info.get('cards', []):
            filepath = card.track_info.get('filepath')
            if filepath:
                self.card_widgets.pop(filepath, None)

        if container := info.get('container'):
            container.deleteLater()
        header.deleteLater()

        if not self.directory_widgets:
            self.main_stack.setCurrentWidget(self.placeholder_widget)
            self.right_click_info_label.hide()
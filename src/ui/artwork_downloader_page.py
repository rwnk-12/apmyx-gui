import os
import re
import requests
import random
import weakref
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QFileDialog, QGridLayout, QSizePolicy, QDialog, QGraphicsBlurEffect, QGraphicsDropShadowEffect,
    QStackedWidget
)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThreadPool, QRunnable, QObject, Qt, QEvent, QTimer, QPointF
from PyQt6.QtGui import QPixmap, QPainter, QColor, QCursor, QPen, QImage

from .search_widgets import SearchLineEdit, LoadingSpinner, ImageFetcher, round_pixmap, MarqueeLabel
from .search_cards import SettingsButton, DownloadIconButton
from enum import Enum

class HeroImageWorkerSignals(QObject):
    finished = pyqtSignal(QPixmap, str)

class HeroImageWorker(QRunnable):
    def __init__(self, image_data, size):
        super().__init__()
        self.signals = HeroImageWorkerSignals()
        self.image_data = image_data
        self.size = size

    @pyqtSlot()
    def run(self):
        pixmap = QPixmap()
        pixmap.loadFromData(self.image_data)
        
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        corner_rect = image.rect().adjusted(0, 0, -image.width() * 3 // 4, -image.height() * 3 // 4)
        total_lum = 0
        if corner_rect.width() > 0 and corner_rect.height() > 0:
            for y in range(corner_rect.top(), corner_rect.bottom()):
                for x in range(corner_rect.left(), corner_rect.right()):
                    total_lum += QColor(image.pixel(x, y)).lightness()
            avg_lum = total_lum / (corner_rect.width() * corner_rect.height())
        else:
            avg_lum = 128

        if avg_lum > 160:
            menu_style = "border: none; border-radius: 8px; QToolTip { color: #222; }"
        else:
            menu_style = "border: none; border-radius: 8px; QToolTip { color: #eee; }"

        scaled = pixmap.scaled(self.size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        self.signals.finished.emit(scaled, menu_style)

class ImageViewer(QDialog):
    download_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")
        self.artwork_data = None

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.image_label, 1)

        self.spinner = LoadingSpinner(self)
        self.spinner.setFixedSize(64, 64)
        self.spinner.hide()

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.download_button = QPushButton("Download")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setFixedSize(120, 36)
        self.download_button.setStyleSheet("""
            QPushButton { background-color: #f77479; color: white; border: none; border-radius: 18px; font-weight: bold; }
            QPushButton:hover { background-color: #f88a8f; }
        """)
        self.download_button.clicked.connect(self._on_download)
        buttons_layout.addWidget(self.download_button)

        self.close_button = QPushButton("Close")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFixedSize(120, 36)
        self.close_button.setStyleSheet("""
            QPushButton { background-color: #d60117; color: white; border: none; border-radius: 18px; font-weight: bold; }
            QPushButton:hover { background-color: #e62237; }
        """)
        self.close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(self.close_button)
        
        self.layout.addLayout(buttons_layout)

        self.thread_pool = QThreadPool.globalInstance()
        self.worker = None

    def show_image(self, artwork_data):
        self.artwork_data = artwork_data
        high_res_url = self.artwork_data.get('artworkUrl', '')
        if not high_res_url:
            return

        self.resize(self.parentWidget().size())
        self.spinner.move(
            (self.width() - self.spinner.width()) // 2,
            (self.height() - self.spinner.height()) // 2
        )
        self.spinner.start()
        self.image_label.clear()

        self.worker = ImageFetcher(high_res_url)
        self.worker.signals.image_loaded.connect(self._on_image_loaded)
        self.worker.signals.error.connect(self._on_load_error)
        self.thread_pool.start(self.worker)
        
        self.exec()

    def _on_download(self):
        if not self.artwork_data:
            return
        
        high_res_url = self.artwork_data.get('artworkUrl', '')
        if not high_res_url:
            return
        
        ext = ".png" if 'png' in high_res_url else ".jpg"
        filename = f"cover{ext}"
        
        self.download_requested.emit(high_res_url, filename)

    @pyqtSlot(bytes)
    def _on_image_loaded(self, image_data):
        self.spinner.stop()
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    @pyqtSlot(str)
    def _on_load_error(self, error_str):
        self.spinner.stop()
        self.image_label.setText("Failed to load image.")
        self.image_label.setStyleSheet("color: #f44336; font-weight: bold;")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
        super().closeEvent(event)

class ArtworkDownloadWorkerSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

class ArtworkDownloadWorker(QRunnable):
    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.signals = ArtworkDownloadWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            with requests.get(self.url, stream=True, timeout=30, headers=headers) as r:
                r.raise_for_status()
                with open(self.save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            self.signals.finished.emit(f"Saved to {os.path.basename(self.save_path)}")
        except Exception as e:
            self.signals.error.emit(str(e))

class ArtworkDisplayCard(QWidget):
    download_requested = pyqtSignal(object, str, str)
    artwork_clicked = pyqtSignal(dict)

    def __init__(self, artwork_data, image_pool, parent=None):
        super().__init__(parent)
        self.artwork_data = artwork_data
        self.image_pool = image_pool
        self.setFixedSize(220, 280)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame(self)
        self.container.setObjectName("ArtworkCardContainer")
        self.container.setStyleSheet("""
            #ArtworkCardContainer {
                background-color: #2c2c2c;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
            }
            #ArtworkCardContainer:hover {
                border: 1px solid #555;
            }
        """)
        self.container.installEventFilter(self)
        outer_layout.addWidget(self.container)

        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self.artwork_container = QWidget()
        self.artwork_container.setFixedSize(200, 200)
        self.artwork_container.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.artwork_label = QLabel(self.artwork_container)
        self.artwork_label.setGeometry(0, 0, 200, 200)
        self.artwork_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_label.setStyleSheet("background-color: #333; border-radius: 8px; color: #888; font-weight: bold;")
        self.artwork_label.installEventFilter(self)
        
        self.spinner = LoadingSpinner(self.artwork_container)
        spinner_size = 48
        self.spinner.setGeometry(
            (200 - spinner_size) // 2, 
            (200 - spinner_size) // 2, 
            spinner_size, 
            spinner_size
        )

        self.retry_button = QPushButton("Retry", self.artwork_container)
        self.retry_button.setGeometry(70, 85, 60, 30)
        self.retry_button.setStyleSheet("""
            QPushButton { background-color: #555; color: white; border: 1px solid #666; border-radius: 4px; }
            QPushButton:hover { background-color: #666; }
        """)
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self._fetch_artwork)
        self.retry_button.hide()

        self.dimensions_label = QLabel(self.artwork_container)
        self.dimensions_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 150);
            color: white;
            font-size: 8pt;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 3px;
        """)
        
        attrs = self.artwork_data.get('attributes', {})
        artwork_info = attrs.get('artwork', {})
        width = artwork_info.get('width')
        height = artwork_info.get('height')
        
        if width and height:
            self.dimensions_label.setText(f"{width}x{height}")
            self.dimensions_label.adjustSize()
            margin = 5
            self.dimensions_label.move(
                self.artwork_container.width() - self.dimensions_label.width() - margin,
                margin
            )
            self.dimensions_label.raise_()
        else:
            self.dimensions_label.hide()
        
        main_layout.addWidget(self.artwork_container)

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 0)
        info_layout.setSpacing(8)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        self.title_label = MarqueeLabel(self.artwork_data.get('name', 'Unknown Album'))
        self.title_label.setStyleSheet("font-weight: bold; color: #e0e0e0; background: transparent;")

        self.artist_label = MarqueeLabel(self.artwork_data.get('artist', 'Unknown Artist'))
        self.artist_label.setStyleSheet("color: #aaa; background: transparent;")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.artist_label)
        
        info_layout.addLayout(text_layout, 1)

        self.download_button = DownloadIconButton(self)
        self.download_button.setToolTip("Download Cover")
        self.download_button.clicked.connect(self._on_download)
        info_layout.addWidget(self.download_button, 0, Qt.AlignmentFlag.AlignVCenter)

        main_layout.addLayout(info_layout)

        self._fetch_artwork()

    def set_download_state(self, loading: bool):
        state = DownloadIconButton.State.Loading if loading else DownloadIconButton.State.Idle
        self.download_button.setState(state)

    def eventFilter(self, source, event):
        if hasattr(self, 'artwork_label') and source is self.artwork_label and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.artwork_clicked.emit(self.artwork_data)
                return True
        if source is self.container:
            if hasattr(self, 'title_label') and hasattr(self, 'artist_label'):
                if event.type() == QEvent.Type.Enter:
                    self.title_label.start_animation()
                    self.artist_label.start_animation()
                elif event.type() == QEvent.Type.Leave:
                    self.title_label.stop_animation()
                    self.artist_label.stop_animation()
        return super().eventFilter(source, event)

    def _fetch_artwork(self):
        self.retry_button.hide()
        self.artwork_label.setText("")
        self.spinner.start()

        preview_url = self.artwork_data.get('artworkUrl', '').replace('5000x5000', '400x400')
        if preview_url:
            worker = ImageFetcher(preview_url).auto_cancel_on(self)
            worker.signals.image_loaded.connect(self._set_artwork)
            worker.signals.error.connect(self._on_load_error)
            self.image_pool.start(worker)
        else:
            self._on_load_error("No artwork URL found")

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        self.spinner.stop()
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        scaled = pixmap.scaled(self.artwork_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.artwork_label.setPixmap(round_pixmap(scaled, 8))

    @pyqtSlot(str)
    def _on_load_error(self, error_str):
        self.spinner.stop()
        self.artwork_label.setText("Load Failed")
        self.retry_button.show()

    def _on_download(self):
        high_res_url = self.artwork_data.get('artworkUrl', '')
        if not high_res_url:
            return
        
        ext = ".png" if 'png' in high_res_url else ".jpg"
        filename = f"cover{ext}"
        
        self.download_requested.emit(self, high_res_url, filename)

class ArtworkDownloaderPage(QWidget):
    back_requested = pyqtSignal()
    menu_requested = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        
        self.image_thread_pool = QThreadPool()
        self.image_thread_pool.setMaxThreadCount(6)
        
        self.download_thread_pool = QThreadPool()
        self.download_thread_pool.setMaxThreadCount(2)
        
        self.results_widgets = []
        self.items_to_add = []
        
        self.current_query = None
        self.current_offset = 0
        self.is_loading_more = False
        self.no_more_results = False

        self.setObjectName("ArtworkDownloaderPage")
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.hero = QFrame()
        self.hero.setObjectName("HeroFrame")
        self.hero.installEventFilter(self)

        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(20, 20, 20, 20)

        self.hero_bg = QLabel(self.hero)
        self.hero_bg.setObjectName("HeroBackground")
        self.hero_bg.setGeometry(0, 0, self.hero.width(), self.hero.height())
        blur_effect = QGraphicsBlurEffect()
        blur_effect.setBlurRadius(30)
        self.hero_bg.setGraphicsEffect(blur_effect)

        self.menu_btn = SettingsButton(self.hero)
        self.menu_btn.setToolTip("Menu")
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        hero_layout.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        title_box = QVBoxLayout()
        title_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel("Artwork Downloader")
        title_label.setObjectName("SettingsTitle")
        subtitle_label = QLabel("Find and download original album artwork.")
        subtitle_label.setObjectName("SettingsSubtitle")
        
        for label in (title_label, subtitle_label):
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(10)
            shadow.setColor(QColor(0, 0, 0, 180))
            shadow.setOffset(0, 1)
            label.setGraphicsEffect(shadow)

        title_box.addWidget(title_label, 0, Qt.AlignmentFlag.AlignCenter)
        title_box.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        hero_layout.addLayout(title_box, 1)
        root_layout.addWidget(self.hero)

        self.content_frame = QFrame()
        self.content_frame.installEventFilter(self)
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        
        self.search_bar = SearchLineEdit()
        self.search_bar.setPlaceholderText("Search by Album or Artist")
        self.search_bar.returnPressed.connect(self.perform_search)
        content_layout.addWidget(self.search_bar)

        self.main_stack = QStackedWidget()
        content_layout.addWidget(self.main_stack, 1)

        self.placeholder_widget = self._create_placeholder_widget()
        self.main_stack.addWidget(self.placeholder_widget)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll)
        
        self.results_container = QWidget()
        self.results_layout = QGridLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.scroll_area.setWidget(self.results_container)
        self.main_stack.addWidget(self.scroll_area)
        
        root_layout.addWidget(self.content_frame, 1)

        self.loading_spinner = LoadingSpinner(self)
        self.loading_spinner.setFixedSize(40, 40)
        self.loading_spinner.hide()

        self.image_viewer = ImageViewer(self)
        self.image_viewer.download_requested.connect(lambda u, f: self.on_download_request(url=u, suggested_filename=f, card=None))
        
        self.setStyleSheet("""
            QWidget#ArtworkDownloaderPage { background-color: #262626; color: #e0e0d0; }
            QFrame#HeroFrame { 
                background-color: #2a2a2a;
                border-bottom: 1px solid #444; 
            }
            QLabel#HeroBackground {
                background-color: #2a2a2a;
            }
            QLabel#SettingsTitle { font-size: 22pt; font-weight: 800; color: white; background: transparent; }
            QLabel#SettingsSubtitle { font-size: 9.5pt; color: #b0b0b0; font-weight: normal; background: transparent; }
        """)

    def _create_placeholder_widget(self):
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(25)

        subtitle_label = QLabel("Find and download original album artwork.")
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
            icon_label.setStyleSheet("font-size: 16pt; color: #d60117;")
            text_label = QLabel(text)
            text_label.setWordWrap(True)
            text_label.setStyleSheet("font-size: 11pt; color: #ccc; line-height: 1.5;")
            point_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
            point_layout.addWidget(text_label, 1)
            return point_widget

        info_layout.addWidget(create_info_point("✔", "<b>Search Freely:</b> Enter an album or artist name to find official artwork from the Apple Music catalog."))
        info_layout.addWidget(create_info_point("!", "<b>View & Download:</b> Click any cover to view it. Use the download button to save the original file."))

        content_row_layout = QHBoxLayout()
        content_row_layout.addStretch(1)
        content_row_layout.addLayout(info_layout, 2)
        content_row_layout.addStretch(1)

        main_layout.addStretch(1)
        main_layout.addWidget(subtitle_label)
        main_layout.addLayout(content_row_layout)
        main_layout.addStretch(2)
        
        return widget

    def eventFilter(self, source, event):
        if hasattr(self, 'content_frame') and source is self.content_frame and event.type() == QEvent.Type.Resize:
            self._reflow_grid()
        if hasattr(self, 'hero') and hasattr(self, 'hero_bg') and source is self.hero and event.type() == QEvent.Type.Resize:
            self.hero_bg.setGeometry(0, 0, self.hero.width(), self.hero.height())
        return super().eventFilter(source, event)

    def _update_hero_background(self, results):
        if not results:
            self.hero_bg.setPixmap(QPixmap())
            return

        first_item = random.choice(results)
        url = first_item.get('artworkUrl', '').replace('5000x5000', '200x200')
        if not url:
            return

        worker = ImageFetcher(url)
        worker.signals.image_loaded.connect(self._start_hero_processing)
        self.image_thread_pool.start(worker)

    @pyqtSlot(bytes)
    def _start_hero_processing(self, image_data):
        worker = HeroImageWorker(image_data, self.hero.size())
        worker.signals.finished.connect(self._on_hero_bg_loaded)
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(QPixmap, str)
    def _on_hero_bg_loaded(self, pixmap, menu_style):
        self.hero_bg.setPixmap(pixmap)
        self.menu_btn.setStyleSheet(menu_style)

    def _reflow_grid(self):
        num_columns = max(1, self.scroll_area.width() // 240)
        
        live_widgets = [ref() for ref in self.results_widgets if ref() is not None]
        
        self.results_widgets = [ref for ref in self.results_widgets if ref() is not None]
        
        widgets = []
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if widget := item.widget():
                if widget is not self.loading_spinner:
                    widgets.append(widget)
        
        for i, widget in enumerate(widgets):
            self.results_layout.addWidget(widget, i // num_columns, i % num_columns)

    @pyqtSlot()
    def perform_search(self):
        query = self.search_bar.text().strip()
        if not query:
            return
        
        self.main_stack.setCurrentWidget(self.scroll_area)
        self.current_query = query
        self.current_offset = 0
        self.is_loading_more = True
        self.no_more_results = False
        
        self.search_bar.start_loading()
        self._clear_results()
        self.controller.search_for_artwork(query)

    @pyqtSlot(list)
    def on_search_results(self, results):
        self.search_bar.stop_loading()
        self._clear_results()
        self._update_hero_background(results)

        if not results:
            placeholder = QLabel("No artwork found for your search.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_layout.addWidget(placeholder, 0, 0)
            self.no_more_results = True
        else:
            self.current_offset = len(results)
            self._start_adding_cards(results)
            if len(results) < 50:
                self.no_more_results = True

        self.is_loading_more = False

    @pyqtSlot(list)
    def on_append_search_results(self, new_results):
        self.loading_spinner.stop()
        self.loading_spinner.hide()
        
        if not new_results:
            self.no_more_results = True
        else:
            self.current_offset += len(new_results)
            self._start_adding_cards(new_results)
            if len(new_results) < 50:
                self.no_more_results = True
        
        self.is_loading_more = False

    def on_scroll(self, value):
        if self.is_loading_more or self.no_more_results or not self.current_query:
            return

        scrollbar = self.scroll_area.verticalScrollBar()
        if value >= scrollbar.maximum() - 250:
            self.is_loading_more = True
            
            num_columns = max(1, self.scroll_area.width() // 240)
            current_items = self.results_layout.count()
            row, col = divmod(current_items, num_columns)
            
            self.loading_spinner.setParent(self.results_container)
            self.results_layout.addWidget(self.loading_spinner, row, col, Qt.AlignmentFlag.AlignCenter)
            self.loading_spinner.start()
            
            self.controller.load_more_artwork(self.current_query, self.current_offset)

    def _start_adding_cards(self, results):
        self.items_to_add = results
        QTimer.singleShot(0, self._process_card_chunk)

    def _process_card_chunk(self):
        if not self.items_to_add:
            return
        
        chunk_size = 8
        chunk = self.items_to_add[:chunk_size]
        self.items_to_add = self.items_to_add[chunk_size:]

        num_columns = max(1, self.scroll_area.width() // 240)
        for item_data in chunk:
            card = ArtworkDisplayCard(item_data, self.image_thread_pool)
            card.download_requested.connect(self.on_download_request)
            card.artwork_clicked.connect(self.on_artwork_clicked)
            
            current_items = len([ref for ref in self.results_widgets if ref() is not None])
            row, col = divmod(current_items, num_columns)
            self.results_layout.addWidget(card, row, col)
            
            self.results_widgets.append(weakref.ref(card))
        
        if self.items_to_add:
            QTimer.singleShot(30, self._process_card_chunk)
        
        self._manage_memory_if_needed()

    def _manage_memory_if_needed(self):
        live_widgets = [ref() for ref in self.results_widgets if ref() is not None]
        
        if len(live_widgets) > 200 and not self.is_loading_more and not self.items_to_add:
            old_refs = self.results_widgets[:50]
            self.results_widgets = self.results_widgets[50:]
            
            for ref in old_refs:
                widget = ref()
                if widget:
                    self.results_layout.removeWidget(widget)
                    widget.deleteLater()

    @pyqtSlot(dict)
    def on_artwork_clicked(self, artwork_data):
        self.image_viewer.show_image(artwork_data)

    def _clear_results(self):
        for ref in self.results_widgets:
            widget = ref()
            if widget:
                widget.deleteLater()
        
        self.results_widgets.clear()
        
        if self.loading_spinner.parent() is not None:
            self.loading_spinner.stop()
            self.loading_spinner.setParent(None)

        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

    @pyqtSlot(object, str, str)
    def on_download_request(self, card, url, suggested_filename):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Artwork As...", suggested_filename, "Image Files (*.jpg *.png)"
        )
        if not save_path:
            return

        if card:
            card.set_download_state(True)

        worker = ArtworkDownloadWorker(url, save_path)
        worker.signals.finished.connect(lambda msg, c=card: self._on_card_download_finished(c, msg))
        worker.signals.error.connect(lambda err, c=card: self._on_card_download_error(c, err))
        self.download_thread_pool.start(worker)
        self.statusBar().showMessage(f"Downloading {os.path.basename(save_path)}...", 3000)

    def _on_card_download_finished(self, card, message):
        if card:
            card.set_download_state(False)
        self.statusBar().showMessage(message, 5000)

    def _on_card_download_error(self, card, error_message):
        if card:
            card.set_download_state(False)
        self.statusBar().showMessage(f"Download failed: {error_message}", 5000)

    def statusBar(self):
        return self.window().statusBar()
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog,
    QPushButton, QDialogButtonBox, QSizePolicy, QScrollArea,
    QFrame, QTabWidget, QFormLayout, QApplication, QGraphicsBlurEffect,
    QGraphicsDropShadowEffect, QBoxLayout, QGraphicsOpacityEffect, QLayout
)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QThreadPool, Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF, QObject, QEvent
from PyQt6.QtGui import QPixmap, QBitmap, QPainter, QColor, QLinearGradient, QFontMetrics
import logging
from .search_widgets import LoadingSpinner, ImageFetcher, round_pixmap, ClickableLabel
from .search_cards import TrackItemWidget, DiscographyCellWidget, TracklistButton

class _ElideOnResizeFilter(QObject):
    def __init__(self, label: QLabel, full_text: str, parent=None):
        super().__init__(parent or label)
        self.label = label
        self.full = full_text
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            fm = QFontMetrics(self.label.font())
            self.label.setText(fm.elidedText(self.full, Qt.TextElideMode.ElideRight, self.label.width()))
        return False

class _BottomFadeOverlay(QWidget):
    def __init__(self, parent, fade_height=28):
        super().__init__(parent)
        self._h = fade_height
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

    def resize_for(self, area: QScrollArea):
        r = area.viewport().rect()
        p = area.viewport().mapTo(self.parentWidget(), r.topLeft())
        self.setGeometry(p.x(), p.y() + r.height() - self._h, r.width(), self._h)
        self.raise_()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(31,31,31,  0))
        g.setColorAt(1.0, QColor(31,31,31,220))
        p.fillRect(self.rect(), g)
        p.end()

class CollapsibleSection(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        self.header = QPushButton(title)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setStyleSheet("""
            QPushButton{
                text-align:left; font-weight:600; padding:6px 8px; border:none;
                border-radius:8px; background:rgba(255,255,255,0.06); color:#e0e0e0;
            }
            QPushButton:checked{ background:rgba(255,255,255,0.10); }
        """)
        self.content = QWidget()
        self.content.setMaximumHeight(0)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 4, 8, 6)
        self.content_layout.setSpacing(4)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        lay.addWidget(self.header)
        lay.addWidget(self.content)

        self._anim = QPropertyAnimation(self.content, b"maximumHeight", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.header.toggled.connect(self._toggle)

    def _toggle(self, checked: bool):
        self.content.setMaximumHeight(self.content.sizeHint().height() if checked else 0)
        self._anim.stop()
        self._anim.setStartValue(self.content.maximumHeight())
        self._anim.setEndValue(self.content.sizeHint().height() if checked else 0)
        self._anim.start()

TAG_H = 20
TAG_FONT_PT = 9
TAG_FAMILY = "'Inter Tight', 'Inter', 'Segoe UI', Roboto, Helvetica, Arial"

def _make_tag(text: str, bg="#555", fg="#fff"):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        QLabel {{
            background:{bg}; color:{fg};
            border-radius:9px; padding:2px 6px;
            font: {TAG_FONT_PT}pt; font-family: {TAG_FAMILY}; font-weight:600;
            min-height:{TAG_H}px; max-height:{TAG_H}px;
        }}""")
    lbl.setFixedHeight(TAG_H)
    return lbl

def _make_gold_tag(text: str):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        QLabel {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #E2C25D, stop:0.5 #C7A148, stop:1 #9D7A24);
            color:#ffffff;
            border:1px solid #755915; border-radius:9px; padding:2px 6px;
            font: {TAG_FONT_PT}pt; font-family: 'Inter Tight','Inter','Segoe UI',Roboto,Helvetica,Arial;
            font-weight:600;
            min-height:{TAG_H}px; max-height:{TAG_H}px;
        }}""")
    lbl.setFixedHeight(TAG_H)
    eff = QGraphicsDropShadowEffect(lbl)
    eff.setBlurRadius(6)
    eff.setColor(QColor(230, 190, 80, 120))
    eff.setOffset(0, 0)
    lbl.setGraphicsEffect(eff)
    return lbl

class ArtistHeroWidget(QWidget):
    back_requested = pyqtSignal()
    download_all_requested = pyqtSignal()

    def __init__(self, artist_data, parent=None):
        super().__init__(parent)
        self.artist_data = artist_data
        self.artist_pixmap = None
        self.background_pixmap = None
        self.thread_pool = QThreadPool.globalInstance()
        
        self._rescale_timer = QTimer(self)
        self._rescale_timer.setSingleShot(True)
        self._rescale_timer.setInterval(35)
        self._rescale_timer.timeout.connect(self._apply_scaled_background)
        
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.background_label = QLabel(self)
        self.background_label.setScaledContents(False)

        self.overlay = QWidget(self)

        self.content_container = QWidget(self)
        self.content_container.setStyleSheet("background: transparent;")
        main_layout = QHBoxLayout(self.content_container)
        main_layout.setContentsMargins(30, 40, 30, 20)
        main_layout.setSpacing(30)

        self.back_label = ClickableLabel("← Back to Search", "")
        self.back_label.setParent(self)
        
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

        artwork_container = QWidget()
        artwork_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        artwork_container.setFixedSize(180, 180)
        artwork_layout = QVBoxLayout(artwork_container)
        artwork_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        
        self.artwork_label = QLabel()
        self.artwork_label.setFixedSize(160, 160)
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
            "background-color: #B03634; border: none; border-radius: 14px;"
        )
        self.download_all_btn.clicked.connect(lambda: self.download_all_requested.emit())
        info_layout.addWidget(self.download_all_btn, 0, Qt.AlignmentFlag.AlignLeft)
        
        main_layout.addWidget(info_container, 1)
        main_layout.setAlignment(info_container, Qt.AlignmentFlag.AlignVCenter)
        main_layout.setAlignment(artwork_container, Qt.AlignmentFlag.AlignVCenter)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._fetch_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        self.background_label.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.content_container.setGeometry(rect)
        
        self.back_label.move(30, 15)
        
        w = self.width()
        layout = self.content_container.layout()
        if w < 600 and isinstance(layout, QBoxLayout):
            layout.setDirection(QBoxLayout.Direction.TopToBottom)
        else:
            layout.setDirection(QBoxLayout.Direction.LeftToRight)

        self._update_gradient()
        self._rescale_timer.start()

    def _apply_scaled_background(self):
        if self.background_pixmap and not self.background_pixmap.isNull():
            scaled = self.background_pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.background_label.setPixmap(scaled)
        
        self.background_label.lower()
        self.overlay.stackUnder(self.content_container)
        self.content_container.raise_()
        self.back_label.raise_()

    def _update_gradient(self):
        self.overlay.setStyleSheet("""
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0.00 rgba(10,10,10,160),
                stop: 0.60 rgba(10,10,10,100),
                stop: 0.82 rgba(31,31,31,120),
                stop: 1.00 rgba(31,31,31,255)
            );
        """)

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
            
            blur_effect = QGraphicsBlurEffect()
            blur_effect.setBlurRadius(16)
            blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
            self.background_label.setGraphicsEffect(blur_effect)
            
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
class TrackSelectionDialog(QDialog):
    def __init__(self, album_data, parent=None):
        super().__init__(parent)
        self.album_data = album_data
        self.track_widgets = []
        album_attrs = self.album_data.get('albumData', {}).get('attributes', {})
        self.setWindowTitle(f"Select Tracks from '{album_attrs.get('name', 'Album')}'")
        self.setMinimumSize(600, 300)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)

        self.header_widget = self._create_header(album_attrs)
        self.main_layout.addWidget(self.header_widget)

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
        self.track_list_layout.setSpacing(0)
        
        scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(scroll_area)

        self.button_box = QDialogButtonBox()
        self.download_button = self.button_box.addButton("Download Selected", QDialogButtonBox.ButtonRole.ActionRole)
        self.select_all_button = self.button_box.addButton("Select All", QDialogButtonBox.ButtonRole.ActionRole)
        self.close_button = self.button_box.addButton(QDialogButtonBox.StandardButton.Close)
        
        self.download_button.clicked.connect(self.accept)
        self.select_all_button.clicked.connect(self.select_all_tracks)
        self.close_button.clicked.connect(self.reject)
        self.main_layout.addWidget(self.button_box)

        self.populate_tracks()
        self._fetch_artwork(album_attrs)

        QTimer.singleShot(0, self.adjust_dialog_height)

    def adjust_dialog_height(self):
        header_height = self.header_widget.sizeHint().height()
        buttons_height = self.button_box.sizeHint().height()
        tracks_height = self.track_list_layout.sizeHint().height()
        
        margins = self.main_layout.contentsMargins()
        spacing = self.main_layout.spacing()
        
        total_height = header_height + buttons_height + tracks_height + (spacing * 4) + margins.top() + margins.bottom()
        
        final_height = max(300, min(total_height, 700))
        self.setFixedHeight(final_height)

    def _create_header(self, album_attrs):
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.art_label = QLabel()
        self.art_label.setFixedSize(60, 60)
        self.art_label.setStyleSheet("background-color: transparent;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setText("...")
        header_layout.addWidget(self.art_label)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        title_label = QLabel(f"<b>{album_attrs.get('name', 'Unknown Album')}</b>")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 12pt;")

        artist_label = QLabel(f"<i>{album_attrs.get('artistName', 'Unknown Artist')}</i>")
        artist_label.setStyleSheet("color: #ccc; font-size: 10pt;")

        tracks = self.album_data.get('tracks', [])
        total_duration_ms = sum(t.get('trackData', {}).get('attributes', {}).get('durationInMillis', 0) for t in tracks)
        total_seconds = total_duration_ms // 1000
        total_minutes = total_seconds // 60
        
        genre = album_attrs.get('genreNames', [''])[0]
        track_count = len(tracks)
        
        meta_text = f"{genre} • {track_count} tracks • {total_minutes}m"
        meta_label = QLabel(meta_text)
        meta_label.setStyleSheet("color: #aaa; font-size: 9pt;")

        info_layout.addWidget(title_label)
        info_layout.addWidget(artist_label)
        info_layout.addWidget(meta_label)
        
        header_layout.addLayout(info_layout)
        return header_widget

    def _fetch_artwork(self, album_attrs):
        artwork_url = album_attrs.get('artwork', {}).get('url', '').replace('{w}', '120').replace('{h}', '120')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            QThreadPool.globalInstance().start(self.worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            
            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            rounded = round_pixmap(scaled, 6)
            
            self.art_label.setPixmap(rounded)

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
                disc_header = QLabel(f"<b>Disc {disc_num}</b>")
                disc_header.setStyleSheet("font-size: 11pt; margin-top: 10px; margin-bottom: 5px; border-bottom: 1px solid #444; padding-bottom: 5px;")
                self.track_list_layout.addWidget(disc_header)
                current_disc = disc_num

            track_widget = TrackItemWidget(track_probe)
            self.track_list_layout.addWidget(track_widget)
            self.track_widgets.append(track_widget)

    def select_all_tracks(self):
        all_checked = all(widget.is_checked() for widget in self.track_widgets)
        new_state = not all_checked
        for widget in self.track_widgets:
            widget.checkbox.setChecked(new_state)
        self.select_all_button.setText("Deselect All" if new_state else "Select All")

    def get_selected_track_ids(self) -> list[str]:
        selected_ids = []
        for widget in self.track_widgets:
            if widget.is_checked():
                track_id = widget.get_track_id()
                if track_id:
                    selected_ids.append(track_id)
        return selected_ids

class ArtistDiscographyPage(QWidget):
    back_requested = pyqtSignal()
    download_requested = pyqtSignal(list)
    tracklist_requested = pyqtSignal(dict)

    def __init__(self, controller, artist_data: dict, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.artist_data = artist_data
        self.cell_widgets = {}
        self._batch_total = 0

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.hero = ArtistHeroWidget(artist_data, self)
        self.hero.back_requested.connect(self.back_requested.emit)
        self.hero.download_all_requested.connect(self._on_download_all_clicked)
        self.main_layout.addWidget(self.hero)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar { alignment: left; border: none; padding-left: 8px; }
            QTabBar::tab {
                background: transparent;
                color: #bbb;
                padding: 7px 16px;
                margin: 2px 4px;
                font-weight: 600;
                border: none;
                border-radius: 16px;
            }
            QTabBar::tab:hover { color: #fff; }
            QTabBar::tab:selected {
                background-color: #fd576b;
                color: white;
                border-radius: 16px;
            }
        """)
        self.main_layout.addWidget(self.tab_widget)

        self.list_layouts = {}
        self._create_tab("Albums")
        self._create_tab("EPs")
        self._create_tab("Singles")
        self._create_tab("Compilations")
        
        self._add_bottom_controls()

        self.spinner = LoadingSpinner(self)
        self.spinner.setFixedSize(50, 50)
        self.spinner.hide()

        self.controller.artist_discography_loaded.connect(self.populate_album_list)
        self.show_loading_state()
        self.controller.resolve_artist(artist_data.get('appleMusicUrl'))

    def _animate_in_widget(self, w: QWidget, delay_ms: int = 0):
        target_h = max(64, w.sizeHint().height() or 64)
        w.setMaximumHeight(0)

        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        eff.setOpacity(0.0)

        fade = QPropertyAnimation(eff, b"opacity", w)
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        grow = QPropertyAnimation(w, b"maximumHeight", w)
        grow.setDuration(220)
        grow.setStartValue(0)
        grow.setEndValue(target_h)
        grow.setEasingCurve(QEasingCurve.Type.OutCubic)

        if not hasattr(w, "_anims"):
            w._anims = []
        w._anims.extend([fade, grow])

        def start():
            fade.start()
            grow.start()

        QTimer.singleShot(max(1, delay_ms), start)

    def _add_bottom_controls(self):
        self.bottom_bar = QFrame()
        lay = QHBoxLayout(self.bottom_bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        self.bottom_download_btn = QPushButton("Download")
        self.bottom_download_btn.setStyleSheet("font-weight: bold; padding: 6px 12px; background-color: #B03634; border: none; border-radius: 4px;")
        self.bottom_download_btn.clicked.connect(self._on_download_clicked)

        self.bottom_select_all_btn = QPushButton("Select All")
        self.bottom_select_all_btn.setStyleSheet("padding: 6px 12px;")
        self.bottom_select_all_btn.clicked.connect(self._select_all_current)

        self.bottom_deselect_btn = QPushButton("Deselect")
        self.bottom_deselect_btn.setStyleSheet("padding: 6px 12px;")
        self.bottom_deselect_btn.clicked.connect(self._deselect_current)

        lay.addStretch()
        lay.addWidget(self.bottom_download_btn)
        lay.addWidget(self.bottom_select_all_btn)
        lay.addWidget(self.bottom_deselect_btn)

        self.main_layout.addWidget(self.bottom_bar)

    def _get_current_widgets(self):
        cat = self._current_category_name()
        return self.cell_widgets.get(cat, [])

    def _select_all_current(self):
        for w in self._get_current_widgets():
            w.checkbox.setChecked(True)

    def _deselect_current(self):
        widgets = self._get_current_widgets()
        if not widgets:
            return
        all_checked = all(w.is_checked() for w in widgets)
        if all_checked:
            for w in widgets:
                w.checkbox.setChecked(False)
        else:
            for w in widgets:
                if w.is_checked():
                    w.checkbox.setChecked(False)

    def _current_category_name(self):
        title = self.tab_widget.tabText(self.tab_widget.currentIndex()).lower()
        return title if title in ["albums", "eps", "singles", "compilations"] else "albums"

    def _on_download_clicked(self):
        urls = self.get_selected_album_urls()
        if urls:
            self.download_requested.emit(urls)

    def get_all_album_urls(self) -> list[str]:
        urls = []
        for layout in self.list_layouts.values():
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if isinstance(w, DiscographyCellWidget):
                        url = w.get_url()
                        if url:
                            urls.append(url)
        return urls

    def _on_download_all_clicked(self):
        urls = self.get_all_album_urls()
        if not urls:
            return
        btn = self.hero.download_all_btn
        self._batch_total = len(urls)
        btn.setEnabled(False)
        btn.setText(f"Queuing 0/{self._batch_total}...")
        self.download_requested.emit(urls)
        try:
            self.controller.update_status_and_log(f"Queuing {self._batch_total} releases...", "info")
        except Exception:
            pass

    @pyqtSlot(int, int)
    def on_discography_batch_progress(self, done, total):
        if hasattr(self.hero, 'download_all_btn'):
            self.hero.download_all_btn.setText(f"Queuing {done}/{total}...")

    @pyqtSlot(int)
    def on_discography_batch_finished(self, total):
        if hasattr(self.hero, 'download_all_btn'):
            self.hero.download_all_btn.setText("Added to queue.")
            QTimer.singleShot(1500, lambda: (
                self.hero.download_all_btn.setText("Download Discography"),
                self.hero.download_all_btn.setEnabled(True)
            ))

    def show_loading_state(self):
        self.tab_widget.hide()
        spinner_x = (self.width() - self.spinner.width()) // 2
        spinner_y = self.hero.geometry().bottom() + 20
        self.spinner.move(spinner_x, spinner_y)
        self.spinner.start()

    def hide_loading_state(self):
        self.spinner.stop()
        self.tab_widget.show()

    def _create_tab(self, title):
        category = title.lower()
        self.cell_widgets[category] = []
        tab = QWidget()
        self.tab_widget.addTab(tab, title)
        
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 5, 10, 5)
        tab_layout.setSpacing(5)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        container_widget = QWidget()
        list_layout = QVBoxLayout(container_widget)
        list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        list_layout.setSpacing(0)
        list_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(container_widget)
        tab_layout.addWidget(scroll_area)

        self.list_layouts[category] = list_layout

    @pyqtSlot(list)
    def populate_album_list(self, discography: list):
        self.hide_loading_state()
        
        if discography:
            logging.info(f"Received discography data for UI. First item: {discography[0]}")
        else:
            logging.info("Received empty discography data for UI.")

        albums, eps, singles, compilations = [], [], [], []
        for item in discography:
            attrs = item.get('attributes', {})
            if not attrs:
                continue

            if attrs.get('isCompilation'):
                compilations.append(item)
                continue
            
            name = attrs.get('name', '').lower()
            if ' - single' in name or attrs.get('isSingle'):
                singles.append(item)
            elif ' - ep' in name:
                eps.append(item)
            else:
                albums.append(item)

        self._populate_tab_content('albums', sorted(albums, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))
        self._populate_tab_content('eps', sorted(eps, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))
        self._populate_tab_content('singles', sorted(singles, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))
        self._populate_tab_content('compilations', sorted(compilations, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))

    def _populate_tab_content(self, category, items):
        layout = self.list_layouts[category]
        self.cell_widgets[category].clear()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for i, album_data in enumerate(items):
            cell_widget = DiscographyCellWidget(album_data)
            cell_widget.setMinimumHeight(68)
            cell_widget.tracklist_requested.connect(self.tracklist_requested.emit)
            layout.addWidget(cell_widget)
            self.cell_widgets[category].append(cell_widget)
            self._animate_in_widget(cell_widget, delay_ms=40 * i)

            if i < len(items) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setStyleSheet("QFrame { border: none; border-top: 1px solid #333; }")
                layout.addWidget(separator)

        layout.addStretch(1)

    def get_selected_album_urls(self) -> list[str]:
        urls = []
        for layout in self.list_layouts.values():
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, DiscographyCellWidget) and widget.is_checked():
                        urls.append(widget.get_url())
        return urls

class TrackListingDialog(QDialog):
    def __init__(self, album_data, parent=None):
        super().__init__(parent)
        self.album_data = album_data
        album_attrs = self.album_data.get('albumData', {}).get('attributes', {})
        self.setWindowTitle(f"Tracks: {album_attrs.get('name', 'Unknown Album')}")
        self.setMinimumSize(600, 500)
        
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
        header_layout.addWidget(self.art_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        title_label = QLabel(album_attrs.get('name', 'Unknown Album'))
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold;")

        artist_label = QLabel(album_attrs.get('artistName', 'Unknown Artist'))
        artist_label.setStyleSheet("color: #aaa; font-size: 12pt;")
        tracks = self.album_data.get('tracks', [])
        total_duration_ms = sum(t.get('trackData', {}).get('attributes', {}).get('durationInMillis', 0) for t in tracks)
        total_seconds = total_duration_ms // 1000
        total_minutes = total_seconds // 60
        genre = album_attrs.get('genreNames', [''])[0]
        track_count = len(tracks)
        meta_text = f"{genre} • {track_count} tracks • {total_minutes}m"
        meta_label = QLabel(meta_text)
        meta_label.setStyleSheet("color: #aaa; font-size: 10pt;")

        info_layout.addWidget(title_label)
        info_layout.addWidget(artist_label)
        info_layout.addWidget(meta_label)
        header_layout.addLayout(info_layout, 1)

        return header_widget

    def _fetch_artwork(self, album_attrs):
        artwork_url = album_attrs.get('artwork', {}).get('url', '').replace('{w}', '240').replace('{h}', '240')
        if artwork_url:
            self.worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            self.worker.signals.image_loaded.connect(self._set_artwork)
            QThreadPool.globalInstance().start(self.worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)

            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            rounded = round_pixmap(scaled, 8)
            
            self.art_label.setPixmap(rounded)

    def populate_tracks(self, tracks):
        disc_numbers = {t.get('trackData', {}).get('attributes', {}).get('discNumber', 1) for t in tracks}
        is_multi_disc = len(disc_numbers) > 1
        current_disc = -1

        for track_probe in tracks:
            attrs = track_probe.get('trackData', {}).get('attributes', {})
            disc_num = attrs.get('discNumber', 1)
            if is_multi_disc and disc_num != current_disc:
                disc_header = QLabel(f"<b>Disc {disc_num}</b>")
                disc_header.setStyleSheet("font-size: 11pt; margin-top: 10px; margin-bottom: 5px; border-bottom: 1px solid #444; padding-bottom: 5px;")
                self.track_list_layout.addWidget(disc_header)
                current_disc = disc_num

            track_widget = QWidget()
            track_layout = QHBoxLayout(track_widget)
            track_layout.setContentsMargins(5, 2, 5, 2)
            track_layout.setSpacing(10)

            track_num_label = QLabel(f"{attrs.get('trackNumber', 0):02d}")
            track_num_label.setFixedWidth(30)
            track_num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            track_num_label.setStyleSheet("color: #aaa; font-size: 10pt;")
            track_layout.addWidget(track_num_label)

            title_label = QLabel(attrs.get('name', 'Unknown Track'))
            title_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
            track_layout.addWidget(title_label, 1)

            duration_ms = attrs.get('durationInMillis', 0)
            seconds = duration_ms // 1000
            duration_str = f"{seconds // 60}:{seconds % 60:02d}"
            duration_label = QLabel(duration_str)
            duration_label.setStyleSheet("color: #aaa; font-size: 10pt;")
            duration_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            duration_label.setFixedWidth(50)
            track_layout.addWidget(duration_label)

            self.track_list_layout.addWidget(track_widget)

class InfoDialog(QDialog):
    link_copied = pyqtSignal()

    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1f1f1f;
                color: #ffffff;
            }
            
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            
            QFormLayout QLabel {
                color: #e0e0e0;
            }
            
            QLabel[objectName="titleLabel"] {
                color: #ffffff;
            }
            
            QLabel[objectName="artistLabel"] {
                color: #cccccc;
            }
            
            QDialogButtonBox {
                background-color: transparent;
            }
            
            QDialogButtonBox QPushButton {
                background-color: #555555;
                color: #ffffff;
                border: 1px solid #777777;
                border-radius: 6px;
                padding: 8px 16px;
            }
            
            QDialogButtonBox QPushButton:hover {
                background-color: #666666;
            }
            
            QDialogButtonBox QPushButton:default {
                background-color: #fd576b;
                border-color: #fd576b;
            }
            
            QDialogButtonBox QPushButton:default:hover {
                background-color: #fe6b7d;
            }
            
            QFrame[frameShape="4"] {
                color: #555555;
                background-color: #555555;
            }
        """)


        self.item_data = item_data
        self.setWindowTitle("Details")
        
        self.resize(520, 450)
        self.setMinimumSize(350, 300)
        
        self._base_font_size = 10
        
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_dynamic_fonts)
        self._resize_timer.setInterval(150)
        
        self._last_font_sizes = {}
        self._chips_widgets = []

        main_layout = QVBoxLayout(self)
        main_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self.header_widget = self._create_header()
        main_layout.addWidget(self.header_widget)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("QScrollArea { border: none; }")

        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.form_layout.setHorizontalSpacing(15)
        self.form_layout.setVerticalSpacing(4)
        self.form_layout.setContentsMargins(0, 0, 0, 0)

        self._populate_info(self.form_layout)
        content_layout.addWidget(self.form_widget)
        
        self._add_track_qualities_section(content_layout)

        self.notes_section = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_section)
        self.notes_layout.setContentsMargins(0, 8, 0, 0)
        self.notes_layout.setSpacing(4)
        self._add_editorial_notes(self.notes_layout)
        content_layout.addWidget(self.notes_section)

        content_layout.addStretch()

        self._scroll_area.setWidget(self._content_widget)
        main_layout.addWidget(self._scroll_area)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self._button_box.accepted.connect(self.accept)
        main_layout.addWidget(self._button_box)
        
        self._fade = _BottomFadeOverlay(self)
        self._fade.hide()
        self._scroll_area.verticalScrollBar().valueChanged.connect(lambda _: self._update_fade())
        self._scroll_area.viewport().installEventFilter(self)

        self._update_dynamic_fonts()
        QTimer.singleShot(0, self._auto_resize_to_fit)

    def _update_fade(self):
        bar = self._scroll_area.verticalScrollBar()
        show = bar.maximum() > 0 and bar.value() < bar.maximum()
        self._fade.setVisible(show)
        if show:
            self._place_fade()

    def _place_fade(self):
        vp = self._scroll_area.viewport()
        r  = vp.rect()
        top_left = vp.mapTo(self, r.topLeft())
        self._fade.setGeometry(top_left.x(), top_left.y() + r.height() - self._fade._h,
                               r.width(), self._fade._h)
        self._fade.raise_()

    def eventFilter(self, obj, ev):
        if obj is self._scroll_area.viewport() and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._update_fade)
        return super().eventFilter(obj, ev)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._update_fade)

    def _auto_resize_to_fit(self):
        QApplication.processEvents()
        self.layout().activate()
        self._content_widget.adjustSize()

        needed_w = max(self.header_widget.sizeHint().width(),
                       self._content_widget.sizeHint().width(),
                       420)
        needed_h = (self.header_widget.sizeHint().height() +
                    self._content_widget.sizeHint().height() +
                    self._button_box.sizeHint().height() +
                    self.layout().contentsMargins().top() +
                    self.layout().contentsMargins().bottom() +
                    self.layout().spacing() * 3)

        screen = self.windowHandle().screen() if self.windowHandle() else QApplication.primaryScreen()
        avail = screen.availableGeometry()
        max_w = int(avail.width() * 0.9)
        max_h = int(avail.height() * 0.9)

        target_w = min(max(520, needed_w), max_w)
        target_h = min(max(360, needed_h), max_h)

        self.setMaximumSize(max_w, max_h)
        self.resize(target_w, target_h)

        geo = self.frameGeometry()
        geo.moveCenter(avail.center())
        self.move(geo.topLeft())
        QTimer.singleShot(0, self._ensure_chips_visible)

    def _viewport_rect(self):
        vp = self._scroll_area.viewport()
        return vp, vp.rect().width()

    def _chips_overflow_px(self):
        vp, vp_w = self._viewport_rect()
        max_overflow = 0
        for w in getattr(self, "_chips_widgets", []):
            if not w.isVisible():
                continue
            top_left_in_vp = w.mapTo(vp, w.rect().topLeft())
            right_edge = top_left_in_vp.x() + w.width()
            overflow = right_edge + 8 - vp_w
            if overflow > max_overflow:
                max_overflow = overflow
        return max_overflow

    def _ensure_chips_visible(self):
        screen = self.windowHandle().screen() if self.windowHandle() else QApplication.primaryScreen()
        avail = screen.availableGeometry()
        max_w = int(avail.width() * 0.95)
        for _ in range(3):
            QApplication.processEvents()
            self._scroll_area.viewport().updateGeometry()
            QApplication.processEvents()
            overflow = self._chips_overflow_px()
            if overflow <= 0:
                break
            new_w = min(max_w, self.width() + int(max(overflow, 0)))
            if new_w <= self.width():
                break
            self.resize(new_w, self.height())
        geo = self.frameGeometry()
        geo.moveCenter(avail.center())
        self.move(geo.topLeft())

    def _add_track_qualities_section(self, parent_layout):
        tracks = self.item_data.get('tracks_data', [])
        if not tracks:
            return

        self._section = CollapsibleSection(f"Track audio details ({len(tracks)})", self)
        self._section.header.toggled.connect(
            lambda _: QTimer.singleShot(260, lambda: (self._auto_resize_to_fit(), self._ensure_chips_visible())))
        
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0,0,0,0)
        header_layout.setSpacing(6)
        
        track_header = QLabel("Track")
        track_header.setStyleSheet("font-weight:700; color:#ccc;")
        header_layout.addWidget(track_header, 1)
        
        chips_header = QWidget()
        chips_header_layout = QHBoxLayout(chips_header)
        chips_header_layout.setContentsMargins(0,0,0,0)
        chips_header_layout.setSpacing(16)
        
        quality_header = QLabel("Quality")
        quality_header.setStyleSheet("font-weight:700; color:#bbb;")
        
        atmos_header = QLabel('Dolby Atmos<br><span style="font-size:9pt; color:#aaa;">Availability</span>')
        atmos_header.setTextFormat(Qt.TextFormat.RichText)
        atmos_header.setStyleSheet("font-weight:700; color:#bbb; line-height:.95;")
        
        chips_header_layout.addWidget(quality_header)
        chips_header_layout.addWidget(atmos_header)
        
        chips_header.adjustSize()
        chips_header.setMinimumWidth(chips_header.sizeHint().width())
        self._chips_widgets.append(chips_header)
        header_layout.addWidget(chips_header, 0, Qt.AlignmentFlag.AlignRight)
        
        self._section.content_layout.addWidget(header_row)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { border: none; border-top: 1px solid #3b3b3b; }")
        self._section.content_layout.addWidget(separator)

        for t in tracks:
            attrs = t.get('attributes', {})

            row = QWidget()
            row.setMinimumHeight(TAG_H + 6)
            h = QHBoxLayout(row)
            h.setContentsMargins(0,0,0,0)
            h.setSpacing(6)

            num = attrs.get('trackNumber')
            name = attrs.get('name', 'Unknown')
            
            left = QLabel(f"{num:02d}. {name}" if isinstance(num, int) and num > 0 else name)
            left.setStyleSheet("font-weight:600;")
            left.setWordWrap(False)
            left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            h.addWidget(left, 1)

            _full = left.text()
            left.setToolTip(_full)
            flt = _ElideOnResizeFilter(left, _full, left)
            left._elide_filter = flt
            left.installEventFilter(flt)

            chips_box = QWidget()
            chips_lay = QHBoxLayout(chips_box)
            chips_lay.setContentsMargins(0,0,0,0)
            chips_lay.setSpacing(6)
            chips_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

            traits = set(attrs.get('audioTraits', []))
            sr = attrs.get('sampleRateHz')
            bd = attrs.get('bitDepth')

            if not bd:
                if 'hi-res-lossless' in traits:
                    bd = 24
                elif 'lossless' in traits:
                    bd = 16

            parts = []
            if isinstance(bd, int) and bd > 0:
                parts.append(f"{bd}B")
            if isinstance(sr, int) and sr > 0:
                khz = sr / 1000.0
                khz_text = f"{khz:.1f}" if abs(khz - int(khz)) > 1e-3 else f"{int(khz)}"
                parts.append(f"{khz_text}kHz")
            if parts:
                t1 = _make_gold_tag(" . ".join(parts))
                t1.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                t1.setWordWrap(False)
                chips_lay.addWidget(t1)

            t2 = _make_tag("Dolby Atmos", "#616161", "#fff") if 'atmos' in traits else _make_tag("Not Available", "#3d3d3d", "#fff")
            t2.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            t2.setWordWrap(False)
            chips_lay.addWidget(t2)
            
            chips_box.adjustSize()
            chips_box.setMinimumWidth(chips_box.sizeHint().width())
            self._chips_widgets.append(chips_box)

            h.addWidget(chips_box, 0, Qt.AlignmentFlag.AlignRight)
            self._section.content_layout.addWidget(row)

        self._section.content_layout.addStretch(1)
        parent_layout.addWidget(self._section)

    def _create_header(self):
        header_widget = QWidget()
        header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        self.art_label = QLabel()
        self.art_label.setFixedSize(70, 70)
        self.art_label.setStyleSheet("background-color: #333; border-radius: 6px;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setText("...")
        self.art_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(self.art_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(f"{self.item_data.get('name', 'Unknown')}")
        self.title_label.setWordWrap(True)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.title_label)

        self.artist_label = QLabel(f"{self.item_data.get('artist', 'Unknown Artist')}")
        self.artist_label.setObjectName("artistLabel")
        self.artist_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.artist_label)

        self.copy_link_label = ClickableLabel("Copy Link", self.item_data.get('appleMusicUrl'), tooltip="Click to copy link")
        self.copy_link_label.clicked.connect(self._copy_link_to_clipboard)
        self.copy_link_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.copy_link_label)

        header_layout.addLayout(info_layout)

        self._fetch_artwork()
        return header_widget

    def _calculate_font_size(self, base_size):
        width = self.width()
        min_width, max_width = 350, 800
        scale_factor = min(max(width - min_width, 0) / (max_width - min_width), 1.0)
        return int(base_size + (scale_factor * 2))

    def _update_dynamic_fonts(self):
        
        if not hasattr(self, 'title_label'):
            return
            
        title_size = self._calculate_font_size(13)
        if self._last_font_sizes.get('title') != title_size:
            self.title_label.setStyleSheet(f"font-size: {title_size}pt; font-weight: bold; margin: 0px; padding: 0px;")
            self._last_font_sizes['title'] = title_size

        artist_size = self._calculate_font_size(10)
        if self._last_font_sizes.get('artist') != artist_size:
            self.artist_label.setStyleSheet(f"color: #ccc; font-size: {artist_size}pt; font-style: italic; margin: 0px; padding: 0px;")
            self._last_font_sizes['artist'] = artist_size
        
        label_size = self._calculate_font_size(9)
        content_size = self._calculate_font_size(9)
        
        if self._last_font_sizes.get('form_label') != label_size:
            for i in range(self.form_layout.rowCount()):
                label_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
                if label_item and label_item.widget():
                    label_widget = label_item.widget()
                    if isinstance(label_widget, QLabel):
                        label_widget.setStyleSheet(f"font-size: {label_size}pt; font-weight: bold; color: #e0e0e0; margin: 0px; padding: 0px;")
            self._last_font_sizes['form_label'] = label_size

        if self._last_font_sizes.get('form_content') != content_size:
            for i in range(self.form_layout.rowCount()):
                field_item = self.form_layout.itemAt(i, QFormLayout.ItemRole.FieldRole)
                if field_item and field_item.widget():
                    field_widget = field_item.widget()
                    if isinstance(field_widget, QLabel):
                        field_widget.setStyleSheet(f"color: #f8586c; font-size: {content_size}pt; margin: 0px; padding: 0px;")
            self._last_font_sizes['form_content'] = content_size
        
        notes_header_size = self._calculate_font_size(11)
        notes_content_size = self._calculate_font_size(8)
        
        for widget in self.notes_section.findChildren(QLabel):
            if widget.text() == "About":
                if self._last_font_sizes.get('notes_header') != notes_header_size:
                    widget.setStyleSheet(f"font-size: {notes_header_size}pt; margin-top: 6px; margin-bottom: 2px; font-weight: bold; padding: 0px;")
                    self._last_font_sizes['notes_header'] = notes_header_size
            elif widget.objectName() == "notesContent":
                if self._last_font_sizes.get('notes_content') != notes_content_size:
                    widget.setStyleSheet(f"color: #bbb; font-size: {notes_content_size}pt; line-height: 1.3; margin: 0px; padding: 0px;")
                    self._last_font_sizes['notes_content'] = notes_content_size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _copy_link_to_clipboard(self, url):
        if url:
            clipboard = QApplication.instance().clipboard()
            clipboard.setText(url)
            self.link_copied.emit()

            sender = self.sender()
            if isinstance(sender, ClickableLabel):
                original_text = sender.text()
                sender.setText("Copied!")
                t = QTimer(sender)
                t.setSingleShot(True)
                def restore():
                    try:
                        sender.setText(original_text)
                    except RuntimeError:
                        pass
                t.timeout.connect(restore)
                t.start(1500)

    def _fetch_artwork(self):
        artwork_url = self.item_data.get('artworkUrl', '').replace('600x600', '160x160')
        if artwork_url:
            worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            worker.signals.image_loaded.connect(self._set_artwork)
            QThreadPool.globalInstance().start(worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.art_label.setPixmap(round_pixmap(scaled, 6))

    def _add_info_row(self, layout, label_text, value):
        if value:
            label = QLabel(f"{label_text}:")
            
            content = QLabel(str(value))
            content.setWordWrap(True)
            
            layout.addRow(label, content)

    def _populate_info(self, layout):
        data = self.item_data
        item_type = data.get('type')

        self._add_info_row(layout, "Release Date", data.get('releaseDate'))
        self._add_info_row(layout, "Record Label", data.get('recordLabel'))
        self._add_info_row(layout, "Copyright", data.get('copyright'))

        if item_type == 'songs':
            self._add_info_row(layout, "Album", data.get('albumName'))
            self._add_info_row(layout, "Composer", data.get('composerName'))
            self._add_info_row(layout, "ISRC", data.get('isrc'))
            self._add_info_row(layout, "Contains Lyrics", "Yes" if data.get('hasLyrics') else "No")
            self._add_info_row(layout, "Time-Synced Lyrics", "Yes" if data.get('hasTimeSyncedLyrics') else "No")
        else:
            self._add_info_row(layout, "Total Tracks", data.get('trackCount'))
            self._add_info_row(layout, "UPC", data.get('upc'))
            self._add_info_row(layout, "Compilation", "Yes" if data.get('isCompilation') else "No")

        if data.get('genreNames'):
            self._add_info_row(layout, "Genres", ", ".join(data['genreNames']))

        tracks = data.get('tracks_data', [])
        total_tracks = data.get('trackCount') or len(tracks)
        
        if tracks:
            atmos_count = 0
            spatial_count = 0
            common_traits = set(tracks[0].get('attributes', {}).get('audioTraits', [])) if tracks else set()

            for track in tracks:
                track_traits = set(track.get('attributes', {}).get('audioTraits', []))
                if 'atmos' in track_traits:
                    atmos_count += 1
                if 'spatial' in track_traits:
                    spatial_count += 1
                common_traits.intersection_update(track_traits)
            
            trait_map = {'lossy-stereo': 'Standard', 'lossless': 'Lossless', 'hi-res-lossless': 'Hi-Res Lossless'}
            
            final_traits = [trait_map[t] for t in sorted(list(common_traits)) if t in trait_map]

            if atmos_count > 0 and 'atmos' not in common_traits:
                final_traits.append(f"Dolby Atmos ({atmos_count}/{total_tracks} Tracks)")
            elif 'atmos' in common_traits:
                final_traits.append("Dolby Atmos")

            if spatial_count > 0 and 'spatial' not in common_traits:
                final_traits.append(f"Spatial Audio ({spatial_count}/{total_tracks} Tracks)")
            elif 'spatial' in common_traits:
                final_traits.append("Spatial Audio")

            self._add_info_row(layout, "Audio Quality", ", ".join(final_traits))
        elif data.get('audioTraits'):
            formatted_traits = [t.replace('lossy-stereo', 'Standard').replace('lossless', 'Lossless').replace('hi-res-lossless', 'Hi-Res Lossless').replace('atmos', 'Dolby Atmos').replace('spatial', 'Spatial Audio').title() for t in data['audioTraits']]
            self._add_info_row(layout, "Audio Quality", ", ".join(formatted_traits))

        self._add_info_row(layout, "Apple Digital Master", "Yes" if data.get('isAppleDigitalMaster') else "No")

    def _add_editorial_notes(self, layout):
        notes = self.item_data.get('editorialNotes')
        if notes:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            layout.addWidget(line)

            notes_header = QLabel("About")
            layout.addWidget(notes_header)

            notes_label = QLabel(notes)
            notes_label.setWordWrap(True)
            notes_label.setTextFormat(Qt.TextFormat.RichText)
            notes_label.setObjectName("notesContent")
            layout.addWidget(notes_label)
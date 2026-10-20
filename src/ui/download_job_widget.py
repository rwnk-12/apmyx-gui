import time

from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar,
                             QPushButton, QMessageBox, QDialog, QTableWidget,
                             QTableWidgetItem, QHeaderView, QDialogButtonBox, QPlainTextEdit)
from PyQt6.QtCore import (
    Qt, pyqtSlot, QThreadPool, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty, QBuffer,
    QIODevice, QRectF,
)
from PyQt6.QtGui import QPixmap, QFontMetrics, QImageReader, QColorSpace, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer
from .search_widgets import ImageFetcher

class InfoButton(QPushButton):
    _SVG_DATA = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>'''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; border-radius: 9px;")
        self._is_hovering = False
        self._renderer = QSvgRenderer()

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

        if self.isDown():
            bg_color = QColor("#666")
        elif self._is_hovering:
            bg_color = QColor("#5a5a5a")
        else:
            bg_color = QColor("transparent")
        
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())

        icon_color = QColor("#bbb")
        if self._is_hovering:
            icon_color = QColor("#eee")

        svg_data = self._SVG_DATA.replace('currentColor', icon_color.name()).encode('utf-8')
        self._renderer.load(svg_data)
        
        target_rect = self.rect().adjusted(2, 2, -2, -2)
        self._renderer.render(painter, QRectF(target_rect))

class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text
        self.setWordWrap(True)  
        self.updateText()

    def setText(self, text):
        self._text = text
        self.updateText()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateText()

    def updateText(self):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())
        super().setText(elided)

PROGRESS_BAR_STYLESHEET = """
QProgressBar {
    border: 1px solid #555;
    border-radius: 3px;
    background-color: #444;
    text-align: center;
    height: 6px;
}
QProgressBar::chunk {
    background-color: #ff546a;
    border-radius: 3px;  /* Ensure chunk matches bar radius */
    border: 0px;  /* Remove any chunk border to avoid overflow */
}
"""

def format_elapsed(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


class SkippedTracksDialog(QDialog):
    def __init__(self, skipped_tracks, downloaded_count, quality, parent=None, reasons=None):
        super().__init__(parent)
        self.setWindowTitle("Download Job Summary")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
        summary_text = f"Job finished with {downloaded_count} downloaded track(s) and {len(skipped_tracks)} skipped track(s)."
        layout.addWidget(QLabel(summary_text))
        
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Track Name", "Status"])
        table.setRowCount(len(skipped_tracks))
        
        for i, track_name in enumerate(skipped_tracks):
            table.setItem(i, 0, QTableWidgetItem(track_name))
            reason = (reasons or {}).get(track_name)
            status_item = QTableWidgetItem(f"Skipped ({reason})" if reason else f"Skipped (Not in {quality})")
            table.setItem(i, 1, status_item)
        
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

class DownloadJobWidget(QWidget):
    cancel_requested = pyqtSignal(int)
    confirmation_requested = pyqtSignal(int, str)

    def __init__(self, job_id, item_data, main_window_ref, quality_label, parent=None):
        super().__init__(parent)
        self.setObjectName("DownloadJobWidget")
        self.setMinimumHeight(68)
        
        self.job_id = job_id
        self.main_window = main_window_ref
        self.quality_label = quality_label
        self.worker = None
        self.skipped_tracks = []
        self.skip_reasons = {}
        self.item_data = item_data
        self.is_finished = False
        self._log = []
        self._has_error = False
        self._first_progress_seen = False
        self._state = "queued" 
        self._elapsed = 0.0
        self._run_started = None
        
      
        self.job_progress_bar = QProgressBar()
        self.job_progress_bar.setTextVisible(False)
        self.job_progress_bar.setFixedHeight(8)
        self.job_progress_bar.setRange(0, 1000)
        self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET)
        
       
        self._progress_animation = QPropertyAnimation(self, b"progressValue", self)
        self._progress_animation.setDuration(250)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.Linear)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        self.art_label = QLabel()
        self.art_label.setFixedSize(52, 52)
        self.art_label.setStyleSheet("background-color: #333; border-radius: 4px;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.art_label, 0, Qt.AlignmentFlag.AlignTop)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        
        top_row_layout = QHBoxLayout()
        
        title_artist_layout = QVBoxLayout()
        title_artist_layout.setSpacing(0)
        
        self.title_label = ElidedLabel()
        self.title_label.setStyleSheet("font-size: 9pt; font-weight: bold;")
        
        self.artist_label = ElidedLabel()
        self.artist_label.setStyleSheet("color: #aaa; font-size: 8pt; font-style: italic;")
        
        title_artist_layout.addWidget(self.title_label)
        title_artist_layout.addWidget(self.artist_label)
        
        top_row_layout.addLayout(title_artist_layout, 1)
        
        counts_layout = QVBoxLayout()
        counts_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        counts_layout.setSpacing(2)
        
        self.track_count_label = QLabel()
        self.track_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.track_count_label.setStyleSheet("font-size: 8pt;")
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(4)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.info_button = InfoButton()
        self.info_button.setToolTip("Show details")
        self.info_button.setVisible(False)
        self.info_button.clicked.connect(self.show_details)
        buttons_layout.addWidget(self.info_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedSize(55, 20)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555; border: 1px solid #666; border-radius: 10px;
                font-size: 8pt;
            }
            QPushButton:hover { background-color: #666; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.cancel_button.setVisible(True)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        buttons_layout.addWidget(self.cancel_button)
        
        counts_layout.addWidget(self.track_count_label)
        counts_layout.addLayout(buttons_layout)
        
        top_row_layout.addLayout(counts_layout)
        
        self.status_label = QLabel("Queued...")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 8pt;")
        
        self.stream_label = QLabel("Stream: -")
        self.stream_label.setStyleSheet("color: #bbb; font-size: 8pt;")
        
        info_layout.addLayout(top_row_layout)
        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.stream_label)
        info_layout.addWidget(self.job_progress_bar)
        
        main_layout.addLayout(info_layout, 1)
        
        self.set_info(item_data)

    def set_paused_ui(self):
        self._state = "paused"
        self._stop_clock()
        self.status_label.setText("Paused · waiting for wrapper")
        self.status_label.setStyleSheet("font-size: 8pt; color: #ffcc33;")
        self.stream_label.setText("")
        self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#ffcc33")) 
        self._progress_animation.stop()
        self.job_progress_bar.setRange(0, 1000)
        self.job_progress_bar.setValue(1000) 
        self.job_progress_bar.setVisible(True)

    def _stop_clock(self):
        if self._run_started is not None:
            self._elapsed += time.monotonic() - self._run_started
            self._run_started = None

    def set_in_progress_ui(self, label="Downloading..."):
        if self._state == "running":
            return 
        self._state = "running"
        self._run_started = time.monotonic()
        self.status_label.setText(label)
        self.status_label.setStyleSheet("font-size: 8pt;") 
        self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET) 
        self.job_progress_bar.setValue(0)
        self.job_progress_bar.setVisible(True)

    @pyqtProperty(int)
    def progressValue(self):
        return self.job_progress_bar.value()

    @progressValue.setter
    def progressValue(self, value):
        self.job_progress_bar.setValue(value)

    def set_info(self, item_data):
        tracks = item_data.get('tracks', [])
        track_count = len(tracks)
        
        title = "Unknown Title"
        artist = "Unknown Artist"
        artwork_url = ""
        
        album_attrs = item_data.get('albumData', {}).get('attributes', {})

        if item_data.get('_is_single_song', False):
            track_data = tracks[0].get('trackData', {})
            track_attrs = track_data.get('attributes', {})
            
            title = track_attrs.get('name', 'Unknown Song')
            artist = track_attrs.get('artistName', 'Unknown Artist')
            artwork_url = track_attrs.get('artwork', {}).get('url', '').replace('{w}', '128').replace('{h}', '128')
            self.track_count_label.setText("1 track")
        else:
            title = album_attrs.get('name', 'Unknown Album')
            artist = album_attrs.get('artistName', 'Unknown Artist')
            artwork_url = album_attrs.get('artwork', {}).get('url', '').replace('{w}', '128').replace('{h}', '128')
            
            if track_count > 0:
                self.track_count_label.setText(f"{track_count} tracks")
            else:
                self.track_count_label.setText("")

        self.title_label.setText(f"{title}")
        self.artist_label.setText(f"{artist}")
        
        if artwork_url:
            self.worker = ImageFetcher(artwork_url)
            self.worker.signals.image_loaded.connect(self.set_image)
            self.worker.signals.error.connect(self._on_image_error)
            QThreadPool.globalInstance().start(self.worker)

    @pyqtSlot(bytes)
    def set_image(self, image_bytes: bytes | None):
        if not image_bytes:
            self.art_label.setText("...")
            return

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        buffer.write(image_bytes)
        buffer.seek(0)

        reader = QImageReader()
        reader.setDevice(buffer)
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(True)
        
        img = reader.read()
        if img.isNull():
            self.art_label.setText("No Art")
            return

        try:
            if img.colorSpace().isValid() and img.colorSpace() != QColorSpace.SRgb:
                img = img.convertToColorSpace(QColorSpace.SRgb)
        except Exception:
            pass

        target = 52
        dpr = self.devicePixelRatioF()
        scaled = img.scaled(int(target * dpr), int(target * dpr),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)

        pm = QPixmap.fromImage(scaled)
        pm.setDevicePixelRatio(dpr)
        self.art_label.setPixmap(pm)

    @pyqtSlot(str)
    def _on_image_error(self, error_str: str):
        self.art_label.setText("No Art")

    def update_progress(self, status_text, track_percent, overall_percent):
        if self.is_finished:
            return
        
        if self._state != "running":
            self.set_in_progress_ui()

        self.status_label.setText(status_text)

        if track_percent < 0:
            self._progress_animation.stop()
            self.job_progress_bar.setRange(0, 0)
            self.cancel_button.setVisible(True)
            return

        if self.job_progress_bar.maximum() == 0:
            self.job_progress_bar.setRange(0, 1000)
            self.job_progress_bar.setValue(int(overall_percent * 10))

        new_target = int(overall_percent * 10)
        current = self.job_progress_bar.value()
        delta = abs(new_target - current)

        if self._progress_animation.state() == QPropertyAnimation.State.Running:
            self._progress_animation.stop()

      
        if not self._first_progress_seen:
            self.job_progress_bar.setValue(new_target)
            self.job_progress_bar.repaint()
            self._first_progress_seen = True
            if not self.cancel_button.isVisible():
                self.cancel_button.setVisible(True)
            return

       
        if delta <= 6:  
            self.job_progress_bar.setValue(new_target)
        else:
            self.job_progress_bar.setValue(new_target)

        if not self.cancel_button.isVisible():
            self.cancel_button.setVisible(True)

    def set_stream_label(self, text: str):
        fixed_text = text
        if 'â€' in text and len(text) > 2:
            try:
                fixed_text = text.encode('latin-1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                fixed_text = (text
                             .replace('â€"', '-')
                             .replace('â€œ', '"')     
                             .replace('â€', '"'))    
        
        self.stream_label.setText(f"Stream: {fixed_text}")

    def add_skipped_track(self, track_name, reason=""):
        if reason:
            self.skip_reasons[track_name] = reason
        if track_name not in self.skipped_tracks:
            self.skipped_tracks.append(track_name)
            self.info_button.setVisible(True)
            self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#ff9800"))

    def append_error_log(self, text: str):
        self._log.append(text)
        self._has_error = True
        self.info_button.setVisible(True)

    def set_finished(self, message, success, skipped_tracks):
        self.is_finished = True
        self._state = "finished"
        self._stop_clock()
        self.cancel_button.setVisible(False)
        saved = success and message.startswith("Saved to ")
        shown = message
        if saved:
            self.status_label.setToolTip(message[len("Saved to "):])
            shown = message.replace("\\", "\\​").replace("/", "/​")
        if success and self._elapsed >= 1:
            shown = f"{shown if saved else shown.rstrip('.')} • {format_elapsed(self._elapsed)}"
        self.status_label.setText(shown)
        self.skipped_tracks = skipped_tracks
        
        if self._progress_animation.state() == QPropertyAnimation.State.Running:
            self._progress_animation.stop()
        
        if self.job_progress_bar.maximum() == 0:
            self.job_progress_bar.setRange(0, 1000)
        
        target_value = 1000
        
        final_anim = QPropertyAnimation(self, b"progressValue", self)
        final_anim.setDuration(150)
        final_anim.setStartValue(self.job_progress_bar.value())
        final_anim.setEndValue(target_value)
        final_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        def set_final_stylesheet():
            if not success and "cancel" in message.lower():
                self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#d32f2f"))  
            elif not success:
                if message:
                    self.append_error_log(message)
                self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#d32f2f"))  
            elif skipped_tracks:
                self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#ff9800"))  
                self.info_button.setVisible(True)
            else:
                self.job_progress_bar.setStyleSheet(PROGRESS_BAR_STYLESHEET.replace("#ff546a", "#4caf50"))  
            
            self.job_progress_bar.setValue(target_value)  
            self.job_progress_bar.repaint()
        
        final_anim.finished.connect(set_final_stylesheet)
        final_anim.start()
        self._final_anim = final_anim  

    def show_details(self):
        if self._has_error:
            dlg = QDialog(self)
            dlg.setWindowTitle("Download Error Details")
            layout = QVBoxLayout(dlg)
            
            view = QPlainTextEdit("\n".join(self._log))
            view.setReadOnly(True)
            view.setStyleSheet("background-color: #2e2e2e; color: #e0e0e0;")
            layout.addWidget(view)
            
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)
            
            dlg.resize(600, 400)
            dlg.exec()
            return
        
        if self.skipped_tracks:
            quality = self.quality_label
            downloaded_count = len(self.item_data.get('tracks', [])) - len(self.skipped_tracks)
            dialog = SkippedTracksDialog(self.skipped_tracks, downloaded_count, quality, self, self.skip_reasons)
            dialog.exec()

    @pyqtSlot()
    def on_cancel_clicked(self):
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("...")
        
        item_name = self.item_data.get('albumData', {}).get('attributes', {}).get('name', 'this download')
        self.confirmation_requested.emit(self.job_id, item_name)

    def closeEvent(self, event):
        self._progress_animation.stop()
        super().closeEvent(event)

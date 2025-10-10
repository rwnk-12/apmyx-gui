from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QStyle
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, pyqtSlot
from .search_cards import PlayButton
from .search_widgets import LoadingSpinner
import logging


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), event.pos().x(), self.width())
            self.setValue(value)
            self.sliderMoved.emit(value)
        super().mousePressEvent(event)


class VideoPreviewDialog(QDialog):
    def __init__(self, video_data, parent=None):
        super().__init__(parent)
        self.video_data = video_data
        attrs = self.video_data.get('attributes', {})
        self.setWindowTitle(f"Preview: {attrs.get('name', 'Music Video')}")
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background-color: #1f1f1f; color: white;")


        self.player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self.player.setAudioOutput(self._audio_output)
        
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)


     
        self.status_label = QLabel("Loading video...", self.video_widget)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("background-color: transparent; color: #aaa; font-size: 14pt;")
        
        self.spinner = LoadingSpinner(self.video_widget)
        self.spinner.setFixedSize(48, 48)
        self.spinner.hide()


        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.video_widget, 1)


        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(10, 5, 10, 5)


        self.play_button = PlayButton()
        self.play_button.setFixedSize(32, 32)
        
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none; height: 4px; background: #444;
                margin: 2px 0; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #e0e0e0; border: none;
                width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
            QSlider::sub-page:horizontal {
                background: #fd576b; border: none;
                height: 4px; border-radius: 2px;
            }
        """)


        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("font-size: 9pt; color: #ccc;")


        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.slider)
        controls_layout.addWidget(self.time_label)
        main_layout.addWidget(controls_widget)


        self.play_button.clicked.connect(self.toggle_playback)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.errorOccurred.connect(self.on_player_error)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.bufferProgressChanged.connect(self.on_buffer_progress_changed)


        self.start_playback()


    def resizeEvent(self, event):
        
        super().resizeEvent(event)
        self.status_label.setGeometry(self.video_widget.rect())
        spinner_x = (self.video_widget.width() - self.spinner.width()) // 2
        spinner_y = (self.video_widget.height() - self.spinner.height()) // 2
        self.spinner.move(spinner_x, spinner_y)


    def start_playback(self):
        previews = self.video_data.get('attributes', {}).get('previews', [])
        if previews:
            preview_url = previews[0].get('url')
            if preview_url:
                logging.info(f"Attempting to play video preview from URL: {preview_url}")
                self.player.setSource(QUrl(preview_url))
                self.player.play() 
            else:
                self.status_label.setText("Error: No preview URL found.")
                logging.error("Video preview failed: No URL in preview data.")
        else:
            self.status_label.setText("Error: No preview data available.")
            logging.error("Video preview failed: No 'previews' array in video data.")


    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()


    @pyqtSlot(QMediaPlayer.PlaybackState)
    def on_playback_state_changed(self, state):
        state_map = {
            QMediaPlayer.PlaybackState.StoppedState: "Stopped",
            QMediaPlayer.PlaybackState.PlayingState: "Playing",
            QMediaPlayer.PlaybackState.PausedState: "Paused",
        }
        logging.info(f"Video player playback state changed: {state_map.get(state, 'Unknown')}")


        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setState(PlayButton.State.Playing)
            self.status_label.hide()
            self.spinner.stop()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.play_button.setState(PlayButton.State.Paused)
        else:
            self.play_button.setState(PlayButton.State.Stopped)


    def on_position_changed(self, position):
        self.slider.setValue(position)
        self.update_time_label()


    def on_duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()


    def update_time_label(self):
        pos = self.player.position() // 1000
        dur = self.player.duration() // 1000
        self.time_label.setText(f"{pos//60}:{pos%60:02d} / {dur//60}:{dur%60:02d}")


    @pyqtSlot(QMediaPlayer.Error, str)
    def on_player_error(self, error, error_string):
        logging.error(f"Video Player Error: {error_string} (Code: {error})")
        self.status_label.setText(f"Error: {error_string}")
        self.status_label.setStyleSheet("background-color: rgba(0,0,0,180); color: red; padding: 10px; font-size: 12pt;")
        self.status_label.setWordWrap(True)
        self.status_label.show()
        self.spinner.stop()


    
    def on_buffer_progress_changed(self, progress: float):
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.BufferingMedia:
            progress_percent = int(progress * 100)
            logging.debug(f"Video buffering progress: {progress_percent}%")
            self.status_label.setText(f"Buffering... {progress_percent}%")
            self.status_label.show()


    @pyqtSlot(QMediaPlayer.MediaStatus)
    def on_media_status_changed(self, status):
        status_map = {
            QMediaPlayer.MediaStatus.NoMedia: "No Media",
            QMediaPlayer.MediaStatus.LoadingMedia: "Loading",
            QMediaPlayer.MediaStatus.LoadedMedia: "Loaded",
            QMediaPlayer.MediaStatus.StalledMedia: "Stalled",
            QMediaPlayer.MediaStatus.BufferingMedia: "Buffering",
            QMediaPlayer.MediaStatus.BufferedMedia: "Buffered",
            QMediaPlayer.MediaStatus.EndOfMedia: "End of Media",
            QMediaPlayer.MediaStatus.InvalidMedia: "Invalid Media",
        }
        logging.info(f"Video player media status changed: {status_map.get(status, 'Unknown')}")


        if status in [QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.StalledMedia]:
            self.spinner.start()
            self.status_label.setText("Buffering...")
            self.status_label.show()
        else:
            self.spinner.stop()


        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            logging.error("Invalid media: The video URL or format may be unsupported.")
            self.status_label.setText("Error: Invalid or unsupported video format.")
            self.status_label.setStyleSheet("background-color: rgba(0,0,0,180); color: red; padding: 10px; font-size: 12pt;")
            self.status_label.show()
        elif status == QMediaPlayer.MediaStatus.LoadedMedia or status == QMediaPlayer.MediaStatus.BufferedMedia:
            self.status_label.hide()
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.player.play()


    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)

import os
import logging
import tempfile
import threading
import requests
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThread, QUrl, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import Qt


logger = logging.getLogger(__name__)

class PreviewDownloaderSignals(QObject):
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(str)
    error = pyqtSignal(str)

class PreviewDownloader(QThread):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.signals = PreviewDownloaderSignals()
        self.temp_file_path = None
        self._should_stop = False

    def run(self):
        tid = threading.get_ident()
        logger.debug(f"PreviewDownloader.run(): start url={self.url} tid={tid}")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_file:
                self.temp_file_path = temp_file.name
            
            with requests.get(self.url, stream=True, timeout=10) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                bytes_downloaded = 0
                
                with open(self.temp_file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if self._should_stop or self.isInterruptionRequested():
                            logger.info("PreviewDownloader.run(): interrupted, cleaning up")
                            self._cleanup()
                            return
                        if chunk:
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            if total_size > 0:
                                progress = int((bytes_downloaded / total_size) * 100)
                                self.signals.download_progress.emit(progress)
            
            if not self._should_stop and not self.isInterruptionRequested():
                logger.debug(f"PreviewDownloader.run(): finished path={self.temp_file_path} tid={tid}")
                self.signals.download_finished.emit(self.temp_file_path)
        except Exception as e:
            if not self._should_stop and not self.isInterruptionRequested():
                logger.error(f"PreviewDownloader.run(): error url={self.url} err={e}", exc_info=True)
                self.signals.error.emit(str(e))
            self._cleanup()

    def _cleanup(self):
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.remove(self.temp_file_path)
                logger.debug(f"PreviewDownloader._cleanup(): removed {self.temp_file_path}")
            except OSError as e:
                logger.warning(f"PreviewDownloader._cleanup(): could not remove {self.temp_file_path}: {e}")
        self.temp_file_path = None

    def stop(self):
        logger.debug("PreviewDownloader.stop(): setting stop flag and requesting interruption")
        self._should_stop = True
        self.requestInterruption()

class Player(QObject):
    StoppedState, PlayingState, PausedState, LoadingState = range(4)
    
    state_changed = pyqtSignal(int, str)
    position_changed = pyqtSignal(int, int)
    track_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_state = self.StoppedState
        self.current_track_data = None
        self.current_preview_file = None
        self.download_thread = None
        self._stopping = False
        self._is_destroyed = False
        
        self.previews_dir = os.path.join(tempfile.gettempdir(), "apmyx_previews")
        os.makedirs(self.previews_dir, exist_ok=True)
        
       
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.75)
        
        
        self._player.playbackStateChanged.connect(
            self._on_player_state_changed, 
            Qt.ConnectionType.QueuedConnection
        )
        self._player.positionChanged.connect(
            self._on_position_changed, 
            Qt.ConnectionType.QueuedConnection
        )
        self._player.errorOccurred.connect(
            self._on_error, 
            Qt.ConnectionType.QueuedConnection
        )
        self._player.mediaStatusChanged.connect(
            self._on_media_status_changed, 
            Qt.ConnectionType.QueuedConnection
        )
        
        logger.info(f"Player.__init__(): previews_dir={self.previews_dir} thread={threading.get_ident()}")

    def play(self, track_data):
        if self._is_destroyed:
            return
            
        preview_url = track_data.get('previewUrl')
        song_url = track_data.get('appleMusicUrl')
        logger.debug(f"Player.play(): state={self.current_state} song_url={song_url} preview_url={preview_url}")

        if not preview_url or not song_url:
            logger.warning("Player.play(): missing previewUrl or appleMusicUrl")
            return

        if self.current_track_data and self.current_track_data.get('appleMusicUrl') == song_url:
            logger.debug(f"Player.play(): toggle same track; backendState={self._player.playbackState()}")
            if self.current_state == self.PlayingState:
                self._player.pause()
            elif self.current_state == self.PausedState:
                self._player.play()
            elif self.current_state == self.StoppedState:
                self._start_playback(track_data)
        else:
            self._start_playback(track_data)

    def _start_playback(self, track_data):
        if self._is_destroyed:
            return
            
        logger.debug(f"Player._start_playback(): entering; stopping prev={bool(self.current_track_data)}")
        self.stop(clear_track=False)

        self.current_track_data = track_data
        self.track_changed.emit(track_data)
        self._set_state(self.LoadingState)

        self.download_thread = PreviewDownloader(track_data['previewUrl'])
        self.download_thread.signals.download_finished.connect(
            self._on_download_finished, 
            Qt.ConnectionType.QueuedConnection
        )
        self.download_thread.signals.error.connect(
            self._on_download_error, 
            Qt.ConnectionType.QueuedConnection
        )
        self.download_thread.start()
        logger.debug("Player._start_playback(): download_thread started")

    def stop(self, clear_track=True):
        if self._stopping or self._is_destroyed:
            logger.debug("Player.stop(): already stopping or destroyed, return early")
            return
        
        self._stopping = True
        
        try:
            logger.debug(f"Player.stop(): begin clear_track={clear_track} backendState={self._player.playbackState()}")
            
         
            if self.download_thread and self.download_thread.isRunning():
                logger.debug("Player.stop(): stopping download thread")
                self.download_thread.stop()
                if not self.download_thread.wait(3000):  
                    logger.warning("Player.stop(): download thread did not stop gracefully")
                    self.download_thread.terminate()
                    self.download_thread.wait(1000)
                self.download_thread = None

           
            if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
                try:
                    logger.debug("Player.stop(): calling backend stop()")
                    self._player.stop()
                except Exception as e:
                    logger.error(f"Player.stop(): backend stop() raised: {e}", exc_info=True)

          
            QTimer.singleShot(50, self._clear_media_source)

            
            self._cleanup_current_preview()

           
            if clear_track:
                logger.debug("Player.stop(): clearing current_track_data")
                self.current_track_data = None

         
            self._set_state(self.StoppedState)
            logger.debug("Player.stop(): finished")
            
        except Exception as e:
            logger.error(f"Player.stop(): unexpected error: {e}", exc_info=True)
        finally:
            self._stopping = False

    def _clear_media_source(self):
        """Safely clear the media source to avoid crashes"""
        if self._is_destroyed:
            return
        try:
            logger.debug("Player._clear_media_source(): clearing media source")
            self._player.setSource(QUrl())
        except Exception as e:
            logger.error(f"Player._clear_media_source(): error clearing source: {e}", exc_info=True)

    def seek(self, position):
        if not self._is_destroyed:
            logger.debug(f"Player.seek(): position={position}")
            self._player.setPosition(position)

    def set_volume(self, volume):
        if not self._is_destroyed:
            logger.debug(f"Player.set_volume(): volume={volume}")
            self._audio_output.setVolume(volume / 100.0)

    @pyqtSlot(str)
    def _on_download_finished(self, file_path):
        if self._is_destroyed or self._stopping:
            return
        logger.debug(f"Player._on_download_finished(): file_path={file_path}")
        self.current_preview_file = file_path
        try:
            self._player.setSource(QUrl.fromLocalFile(file_path))
            self._player.play()
        except Exception as e:
            logger.error(f"Player._on_download_finished(): error setting source: {e}", exc_info=True)
            self.stop()

    @pyqtSlot(str)
    def _on_download_error(self, error_string):
        if self._is_destroyed:
            return
        logger.error(f"Player._on_download_error(): {error_string}")
      
        QTimer.singleShot(0, self.stop)

    @pyqtSlot(QMediaPlayer.PlaybackState)
    def _on_player_state_changed(self, state):
        if self._is_destroyed or self._stopping:
            return
        logger.debug(f"Player._on_player_state_changed(): state={state} current_state={self.current_state}")
        
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._set_state(self.PlayingState)
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._set_state(self.PausedState)
        elif state == QMediaPlayer.PlaybackState.StoppedState:
    
            if self.current_state != self.StoppedState and not self._stopping:
                logger.debug("Player._on_player_state_changed(): setting state to stopped")
                self._set_state(self.StoppedState)

    @pyqtSlot(QMediaPlayer.MediaStatus)
    def _on_media_status_changed(self, status):
        if self._is_destroyed:
            return
        logger.debug(f"Player._on_media_status_changed(): status={status}")
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            logger.debug("Player._on_media_status_changed(): EndOfMedia -> defer stop()")
           
            QTimer.singleShot(100, self.stop)

    @pyqtSlot('qint64')
    def _on_position_changed(self, position):
        if self._is_destroyed:
            return
        duration = self._player.duration()
        if position == 0 or (position % 1000) < 50:
            logger.debug(f"Player._on_position_changed(): pos={position} dur={duration}")
        if self.current_state == self.PlayingState:
            self.position_changed.emit(int(position), int(duration))

    @pyqtSlot(QMediaPlayer.Error, str)
    def _on_error(self, error, error_string):
        if self._is_destroyed:
            return
        logger.error(f"Player._on_error(): code={error} msg={error_string}")
        
        QTimer.singleShot(0, self.stop)

    def _set_state(self, state):
        if self._is_destroyed or self.current_state == state:
            return
        prev = self.current_state
        self.current_state = state
        song_url = self.current_track_data.get('appleMusicUrl') if self.current_track_data else ""
        logger.debug(f"Player._set_state(): {prev} -> {state} url={song_url}")
        self.state_changed.emit(self.current_state, song_url)

    def _cleanup_current_preview(self):
        if self.current_preview_file:
            fp = self.current_preview_file
            self.current_preview_file = None
            logger.debug(f"Player._cleanup_current_preview(): schedule delete {fp}")
            # Delay file deletion to ensure it's not in use
            QTimer.singleShot(200, lambda: self._delete_preview_file(fp))

    def _delete_preview_file(self, filepath):
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Player._delete_preview_file(): removed {filepath}")
            except OSError as e:
                logger.warning(f"Player._delete_preview_file(): could not remove {filepath}: {e}")

    def _cleanup_all_previews(self):
        logger.info("Player._cleanup_all_previews(): begin")
        if not os.path.exists(self.previews_dir):
            return
        try:
            for filename in os.listdir(self.previews_dir):
                file_path = os.path.join(self.previews_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                        logger.debug(f"Player._cleanup_all_previews(): removed {file_path}")
                except Exception as e:
                    logger.error(f"Player._cleanup_all_previews(): failed {file_path}: {e}")
        except Exception as e:
            logger.error(f"Player._cleanup_all_previews(): error listing directory: {e}")

    def cleanup(self):
        logger.info("Player.cleanup(): begin")
        self._is_destroyed = True
        
        # Stop everything first
        self.stop()
        
        # Disconnect all signals to prevent callbacks after cleanup
        try:
            self._player.playbackStateChanged.disconnect()
            self._player.positionChanged.disconnect()
            self._player.errorOccurred.disconnect()
            self._player.mediaStatusChanged.disconnect()
        except Exception as e:
            logger.debug(f"Player.cleanup(): error disconnecting signals: {e}")
        
        # Clean up all preview files
        self._cleanup_all_previews()
        
        logger.info("Player.cleanup(): end")

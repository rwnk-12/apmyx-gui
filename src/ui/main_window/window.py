import os
import sys
import logging
import multiprocessing
import subprocess
import yaml
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QMainWindow, QWidget,
    QStatusBar, QLabel, QLayout,
    QApplication, QDialog
)
from PyQt6.QtCore import pyqtSignal, QTimer, QThreadPool, pyqtSlot, QSettings
from PyQt6.QtGui import QAction
from ..preview_player import Player
from core.download_worker import DownloadWorker
from .player_bar import PlayerBar
from ..search_cards import LoadingTile, PlayButton
from ..queue_panel import QueuePanel
from ..view_select import SelectionDropdown
from .dialogs import RestartDialog, StorefrontRequiredDialog
from ..video_preview_dialog import VideoPreviewDialog
from .mixins.ui_setup_features import UiSetupFeatures
from .mixins.layout_animation_features import LayoutAnimationFeatures
from .mixins.search_features import SearchFeatures
from .mixins.signal_handlers_features import SignalHandlersFeatures
from .mixins.player_features import PlayerFeatures
from .mixins.selection_features import SelectionFeatures

class MainWindow(QMainWindow, UiSetupFeatures, LayoutAnimationFeatures, SearchFeatures, SignalHandlersFeatures, PlayerFeatures, SelectionFeatures):
    trigger_download_job = pyqtSignal(int, dict, str, str)
    discography_batch_progress = pyqtSignal(int, int)
    discography_batch_finished = pyqtSignal(int)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("apmyx")
        self.setGeometry(100, 100, 1280, 800)
        self.setMinimumSize(800, 600)
        self.GEOMETRY_SETTING = "MainWindow/geometry"
        self.STATE_SETTING = "MainWindow/state"
        self._current_page_with_menu_signal = None
        self.job_counter = 0
        self.is_welcome_view = False
        self.selection_manager = {}
        self.card_widgets = {}
        self._disco_batch = None
        self._info_dialog_open = False
        self._is_panel_animating = False
        self._is_shutting_down = False
        self.songs_view_mode = 'list'
        self.list_loading_indicator = None
        self.storefront_change_count = 0
        self._pending_song_by_job = {}
        self.sidebar_open = False
        self.queue_open = False
        self._sidebar_prev_open = None
        self._queue_prev_open = None
        self.download_worker = DownloadWorker(self.controller.downloader_executable, self.controller)
        self.current_query = None
        self.search_cache = {}
        self.search_offsets = {}
        self.is_loading_more = {}
        self.is_initial_loading = {}
        self.no_more_results = {}
        self.scroll_areas = {}
        self.tab_containers = {}
        self.albums_tab_searched = False
        self.music_videos_tab_searched = False
        self.playlists_tab_searched = False
        self.loading_spinners = {}
        self.active_card = None
        self.loading_tile = LoadingTile(self)
        self.loading_tile.hide()
        QThreadPool.globalInstance().setMaxThreadCount(4)
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow_all_grids)
        self.player = Player(self)
        if hasattr(self.player, 'previews_dir'):
            self.player._cleanup_all_previews()
        self.active_playback_card_url = None
        self.player_state_to_button_state = {
            Player.StoppedState: PlayButton.State.Stopped,
            Player.PlayingState: PlayButton.State.Playing,
            Player.PausedState: PlayButton.State.Paused,
            Player.LoadingState: PlayButton.State.Loading,
        }
        self.setup_ui()
        self.setup_worker_connections()
        QTimer.singleShot(0, self._load_initial_settings)
        self.pending_song_id = None
        self.track_selection_dialog = None
        self.search_action = QAction(self)
        self.spinner_action = None
        self.spinner_movie = None
        QTimer.singleShot(0, self.search_input.line_edit.setFocus)
        self.restore_window_state()

    def restore_window_state(self):
        settings = QSettings()
        geometry = settings.value(self.GEOMETRY_SETTING, b'')
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value(self.STATE_SETTING, b'')
        if state:
            self.restoreState(state)

    def save_window_state(self):
        settings = QSettings()
        settings.setValue(self.STATE_SETTING, self.saveState())
        settings.setValue(self.GEOMETRY_SETTING, self.saveGeometry())

    def _load_initial_settings(self):
        valid_qualities = ["Atmos", "ALAC", "AAC"]
        try:
            with open('config.yaml', 'r') as f:
                config = yaml.safe_load(f) or {}
            aac_type = config.get('aac-type', 'aac-lc')
            self.aac_quality_selector.setCurrentText(aac_type)
            preferred_quality = config.get('preferred-quality')
            if preferred_quality in valid_qualities:
                self.quality_selector.setCurrentText(preferred_quality)
                self._on_quality_selection_changed(preferred_quality)
            else:
                logging.warning(f"Invalid preferred-quality '{preferred_quality}' in config; defaulting to 'Atmos'")
                config['preferred-quality'] = 'Atmos'
                with open('config.yaml', 'w') as f:
                    yaml.dump(config, f, sort_keys=False, allow_unicode=True)
                self.quality_selector.setCurrentIndex(0)
                self._on_quality_selection_changed('Atmos')
        except FileNotFoundError:
            config = {'preferred-quality': 'Atmos', 'aac-type': 'aac-lc'}
            with open('config.yaml', 'w') as f:
                yaml.dump(config, f, sort_keys=False, allow_unicode=True)
            self.quality_selector.setCurrentIndex(0)
            self.aac_quality_selector.setCurrentText('aac-lc')
            self._on_quality_selection_changed('Atmos')
        except Exception as e:
            logging.error(f"Failed to load initial settings from config.yaml: {e}")
            self.quality_selector.setCurrentIndex(0)
            self.aac_quality_selector.setCurrentText('aac-lc')
            self._on_quality_selection_changed('Atmos')

    @pyqtSlot()
    def on_force_clear_all_jobs(self):
        logging.info("MainWindow force clearing all job queues.")
        self._disco_batch = None

    def _restart_application(self):
        logging.info("Scheduling application restart...")
        executable = sys.executable
        args = sys.argv
        if sys.platform == "win32":
            subprocess.Popen([executable] + args, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            subprocess.Popen([executable] + args)
        QApplication.instance().quit()

    def _show_restart_popup(self):
        dialog = RestartDialog(self)
        mw_rect = self.geometry()
        dialog.move(mw_rect.center() - dialog.rect().center())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._restart_application()

    def show_storefront_required_dialog(self):
        dialog = StorefrontRequiredDialog(self)
        mw_rect = self.geometry()
        dialog.move(mw_rect.center() - dialog.rect().center())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.open_settings_page()
            if hasattr(self.settings_page, 'focus_storefront'):
                QTimer.singleShot(100, self.settings_page.focus_storefront)

    def _show_link_spinner(self):
        if hasattr(self.search_input, 'setLoading'):
            self.search_input.setLoading(True)

    def _hide_link_spinner(self):
        if hasattr(self.search_input, 'setLoading'):
            self.search_input.setLoading(False)

    def _set_active_card(self, card):
        if self.active_card and self.active_card != card:
            if hasattr(self.active_card, 'stop_action'):
                self.active_card.stop_action()
        self.active_card = card
        if self.active_card and hasattr(self.active_card, 'start_action'):
            self.active_card.start_action()

    def _clear_active_card(self):
        if self.active_card and hasattr(self.active_card, 'stop_action'):
            self.active_card.stop_action()
        self.active_card = None

    def show_popup(self, message):
        self.popup_label.setText(message)
        self.popup_label.adjustSize()
        popup_x = (self.width() - self.popup_label.width()) // 2
        popup_y = self.height() - self.popup_label.height() - 10
        self.popup_label.move(popup_x, popup_y)
        self.popup_label.show()
        QTimer.singleShot(10000, self.popup_label.hide)

    def update_queue_button(self, count):
        pass

    def _clear_layout(self, layout, delete_widgets=True):
        if layout is not None:
            if self.loading_tile.parent() is not None:
                self.loading_tile.stop()
                self.loading_tile.setParent(None)
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    if delete_widgets:
                        widget.deleteLater()
                    else:
                        widget.setParent(None)
            if delete_widgets and isinstance(layout, QLayout):
                QWidget().setLayout(layout)

    def _update_quality_ui(self):
        pass

    def _position_fetch_popup(self):
        self.fetch_progress_popup.adjustSize()
        popup_x = (self.width() - self.fetch_progress_popup.width()) // 2
        bottom_margin = 30
        if self.player_bar.isVisible():
            bottom_margin += self.player_bar.height()
        popup_y = self.height() - self.fetch_progress_popup.height() - bottom_margin
        self.fetch_progress_popup.move(popup_x, popup_y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_reflow_timer"):
            self._reflow_timer.start(100)
        if self.fetch_progress_popup.isVisible():
            self._position_fetch_popup()

    def closeEvent(self, event):
        self.save_window_state()
        if self._is_shutting_down:
            event.accept()
            return
        self._is_shutting_down = True
        event.ignore()
        try:
            logging.info("Initiating shutdown sequence...")
            if hasattr(self, 'player'):
                self.player.cleanup()
            self.download_worker.cancel_all_jobs()
            logging.info("Waiting for thread pools to shut down...")
            if not self.controller.thread_pool.waitForDone(2000):
                logging.warning("Controller thread pool timeout on shutdown.")
            if not self.download_worker.thread_pool.waitForDone(2000):
                logging.warning("Download worker thread pool timeout on shutdown.")
            if not QThreadPool.globalInstance().waitForDone(2000):
                logging.warning("Global thread pool timeout on shutdown.")
            self._force_terminate_subprocesses()
            self._safe_cleanup_widgets()
            logging.info("Shutdown sequence complete. Scheduling application quit.")
            QTimer.singleShot(0, QApplication.instance().quit)
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")
            os._exit(1)

    def _force_terminate_subprocesses(self):
        for proc in self.controller.active_processes:
            if proc.poll() is None:
                logging.warning(f"Force-terminating lingering subprocess PID {proc.pid}")
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception as e:
                    logging.error(f"Error terminating process {proc.pid}: {e}")

    def _safe_cleanup_widgets(self):
        try:
            self.hide()
            if hasattr(self, 'page_stack'):
                while self.page_stack.count() > 0:
                    widget = self.page_stack.widget(0)
                    self.page_stack.removeWidget(widget)
                    widget.deleteLater()
            if hasattr(self, 'track_selection_dialog') and self.track_selection_dialog:
                self.track_selection_dialog.deleteLater()
        except RuntimeError as e:
            if "wrapped C/C++ object" in str(e):
                logging.warning(f"Ignored widget deletion error during shutdown: {e}")
            else:
                raise
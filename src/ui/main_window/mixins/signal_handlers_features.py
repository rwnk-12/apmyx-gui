import copy
import logging
import sys
import subprocess
import yaml
import json
import time
import re
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QLayout, QApplication, QFileDialog
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
import os
from ..dialogs import RestartDialog, WrapperErrorDialog
from ...artist import ArtistDiscographyPage
from ...track_dialogs import TrackSelectionDialog, TrackListingDialog
from ...info_dialog import InfoDialog
from ...video_preview_dialog import VideoPreviewDialog

class SignalHandlersFeatures:
    """Features for handling signals from controller, workers, and UI components."""

    def setup_worker_connections(self):
        self.controller.search_results_loaded.connect(self.display_search_results)
        self.controller.search_failed.connect(self.on_search_failed)
        self.controller.search_results_appended.connect(self.append_search_results)
        self.controller.category_search_results_loaded.connect(self.handle_category_search_results)
        self.controller.status_updated.connect(self.statusBar().showMessage)
        self.controller.media_details_loaded.connect(self.on_media_details_loaded)
        self.controller.media_fetch_failed.connect(self.on_media_fetch_failed)
        self.controller.media_fetch_progress.connect(self.on_media_fetch_progress)
        self.controller.tracklist_loaded_for_selection.connect(self.open_track_selection_dialog)
        self.controller.tracklist_loaded_for_viewing.connect(self.open_track_listing_dialog)
        self.controller.album_details_for_info_loaded.connect(self.open_album_info_dialog, Qt.ConnectionType.UniqueConnection)
        self.controller.song_details_for_info_loaded.connect(self.open_album_info_dialog, Qt.ConnectionType.UniqueConnection)
        self.controller.track_qualities_loaded.connect(self.on_track_qualities_loaded)
        self.controller.force_clear_all_jobs.connect(self.on_force_clear_all_jobs)
        self.controller.video_details_for_preview_loaded.connect(self.on_video_details_for_preview_loaded)
        self.controller.artwork_search_results_loaded.connect(self.artwork_page.on_search_results)
        self.controller.artwork_search_results_appended.connect(self.artwork_page.on_append_search_results)
        self.controller.local_scan_results.connect(self.lyrics_page.on_scan_results)
        self.controller.lyrics_download_finished.connect(self.lyrics_page.on_lyrics_download_finished)

        self.trigger_download_job.connect(self.download_worker.add_job_to_queue)
        self.download_worker.job_progress.connect(self.update_job_progress)
        self.download_worker.track_skipped.connect(self.queue_panel.handle_track_skipped)
        self.download_worker.job_finished.connect(self.queue_panel.finalize_job)
        self.download_worker.queue_status_update.connect(self.update_queue_button)
        self.download_worker.job_cancelled.connect(self.queue_panel.cancel_job)
        self.download_worker.job_error_line.connect(self.queue_panel.handle_job_error_line)
        self.download_worker.job_stream_label.connect(self.queue_panel.update_stream_label)
        self.download_worker.job_error_line.connect(self._maybe_show_decryptor_popup)
        self.download_worker.queue_has_been_paused.connect(self._on_queue_pause_triggered)
        self.download_worker.job_started.connect(self._on_job_started)

        self.search_input.returnPressed.connect(self.handle_input)
        self.settings_button.clicked.connect(self.toggle_sidebar)
        self.settings_page.settings_applied.connect(self.on_settings_applied, Qt.ConnectionType.UniqueConnection)
        self.download_selected_button.clicked.connect(self._on_download_selected_clicked)
        self.selection_dropdown.remove_single_item_requested.connect(self._remove_single_selection)
        self.selection_dropdown.clear_all_requested.connect(self._clear_selection)
        self.selection_dropdown.clear_selected_requested.connect(self._on_clear_selected_requested)

        self.queue_panel.job_cancellation_requested.connect(self._on_cancel_job)
        self.queue_panel.cancel_all_requested.connect(self.download_worker.cancel_all_jobs)
        self.queue_panel.resume_button.clicked.connect(self._on_manual_resume)
        self.queue_panel.clear_paused_button.clicked.connect(self._on_clear_paused)
        
        self.quality_selector.selectionChanged.connect(self._on_quality_selection_changed)
        self.aac_quality_selector.currentTextChanged.connect(self._on_aac_type_changed)
        
        self.player.track_changed.connect(self.on_player_track_changed)
        self.player.state_changed.connect(self.on_player_state_changed)
        self.player.position_changed.connect(self.player_bar.update_progress)
        self.player_bar.play_toggled.connect(self.on_player_bar_play_toggled)
        self.player_bar.seek_requested.connect(self.player.seek)
        self.player_bar.volume_changed.connect(self.player.set_volume)
        self.player_bar.close_requested.connect(self.on_player_bar_close_requested)

        self.controller.lyrics_download_started.connect(lambda item_id: self._show_download_spinner(item_id))
        self.controller.lyrics_content_ready_for_save.connect(self.on_lyrics_content_ready_for_save)
        self.controller.artwork_download_started.connect(lambda item_id: self._show_download_spinner(item_id))
        self.controller.artwork_download_finished.connect(self.on_artwork_download_finished)

        self._on_quality_selection_changed(self.quality_selector.currentText())
        
       
        self.queue_is_paused = False
        self._paused_jobs = []
        self._cleanup_legacy_pause_file()

        
        self._wrapper_popup = None
        self._last_wrapper_popup_ts = 0

    def _cleanup_legacy_pause_file(self):
        """On startup, removes the old persistence file if it exists from previous versions."""
        try:
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:

                app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            
  
            persistence_dir = os.path.join(app_dir, 'persistence')
            legacy_file = os.path.join(persistence_dir, 'paused_queue.json')
            
            if os.path.exists(legacy_file):
                os.remove(legacy_file)
                logging.info(f"Removed legacy paused queue file: {legacy_file}")
        except Exception as e:
            logging.warning(f"Could not clean up legacy pause file: {e}")

    def _paused_remove_by_id(self, job_id: int) -> bool:
        """Removes a job from the in-memory paused list by its ID."""
        initial_len = len(self._paused_jobs)
        self._paused_jobs = [job for job in self._paused_jobs if job.get('job_id') != job_id]
        return len(self._paused_jobs) < initial_len

    @pyqtSlot(int)
    def _on_cancel_job(self, job_id: int):
        """Handles cancellation for any job, whether paused, queued, or running."""
 
        self._paused_remove_by_id(job_id)

  
        self.download_worker.cancel_job(job_id)

        
        if job_id in self.queue_panel.jobs:
            self.queue_panel.remove_job(job_id)

        if self.queue_is_paused and not self._paused_jobs:
            logging.info("Last paused item cancelled. Resuming queue.")
            self.queue_is_paused = False
            self.queue_panel.hide_pause_banner()
         
            if self.download_worker.has_pending():
                self.download_worker.resume_queue()

    @pyqtSlot(list)
    def _on_queue_pause_triggered(self, paused_jobs: list):
        """Handles the signal from the worker that the queue has been paused."""
        if self.queue_is_paused:
            return
        
        logging.warning("Queue pause triggered by worker. Storing state in memory.")
        self.queue_is_paused = True
        self._paused_jobs = paused_jobs 
 
        for job_dict in paused_jobs:
            job_id = job_dict['job_id']
            widget = self.queue_panel.get_job_widget(job_id)
            if widget:
                widget.set_paused_ui()
        
        self.queue_panel.show_pause_banner(len(paused_jobs))
        self.statusBar().showMessage("Queue paused due to wrapper/decryptor error.", 5000)

        try:
            job_id = paused_jobs[0]['job_id'] if paused_jobs else -1
            self._maybe_show_decryptor_popup(job_id, "Connection refused on 127.0.0.1:10020")
        except Exception as e:
            logging.error(f"Error showing wrapper popup from pause trigger: {e}")

    @pyqtSlot(int)
    def _on_job_started(self, job_id: int):
        """Fired when a job is taken from the queue to be processed."""
        widget = self.queue_panel.get_job_widget(job_id)
        if widget:
            widget.set_in_progress_ui("Starting...")

    @pyqtSlot()
    def _on_manual_resume(self):
        """Handles the 'Resume' button click on the pause banner."""
        if not self._paused_jobs:
            self._clear_paused_state()  
            return
        
        logging.info(f"User resuming queue with {len(self._paused_jobs)} jobs.")
        

        for job_dict in self._paused_jobs:
            self.download_worker.add_job_to_queue(
                job_dict['job_id'],
                job_dict['media_data'],
                job_dict['quality'],
                job_dict['original_url']
            )
        

        self.download_worker.resume_queue()
        self._clear_paused_state()
        self.statusBar().showMessage("Queue resumed.", 3000)

    @pyqtSlot()
    def _on_clear_paused(self):
        """Handles the 'Clear Paused' button click."""
        logging.info("User clearing paused queue.")
        

        for job_dict in self._paused_jobs:
            job_id = job_dict['job_id']
            if job_id in self.queue_panel.jobs:
                self.queue_panel.remove_job(job_id)
                
        self._clear_paused_state()
        self.statusBar().showMessage("Paused queue cleared.", 3000)

    def _clear_paused_state(self):
        """Resets the in-memory pause state and updates the UI."""
        self._paused_jobs = []
        self.queue_is_paused = False
        self.queue_panel.hide_pause_banner()

        if self.download_worker.queue_paused:
            self.download_worker.resume_queue()

    @pyqtSlot(str)
    def _on_quality_selection_changed(self, text: str):
        self.statusBar().showMessage(f"Preferred quality: {text}", 1500)
        is_aac = "aac" in text.lower()
        self.aac_quality_selector.setVisible(is_aac)
        if hasattr(self, 'quality_info_badge'):
       
            new_text = "Token Required. Click here to set it up if not already configured." if is_aac else "Make sure wrapper is running."
            tooltip = "Apple Music web token required for AAC downloads" if is_aac else "Wrapper (decryptor) required for ALAC and Dolby Atmos downloads"
            
 
            self.quality_info_badge.setText(new_text)
            self.quality_info_badge.setToolTip(tooltip)

   
            fm = self.quality_info_badge.fontMetrics()
            text_w = fm.horizontalAdvance(self.quality_info_badge.text())
            icon_w = 14      
            spacing = 6     
            hpad = 10 * 2    
            self.quality_info_badge.setMinimumWidth(text_w + icon_w + spacing + hpad)
            
           
            self.quality_info_badge.updateGeometry()

        try:
            with open('config.yaml', 'r') as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}
        
        if config.get('preferred-quality') != text:
            config['preferred-quality'] = text
            try:
                with open('config.yaml', 'w') as f:
                    yaml.dump(config, f, sort_keys=False, allow_unicode=True)
            except Exception as e:
                logging.error(f"Failed to save preferred quality to config.yaml: {e}")
                self.statusBar().showMessage(f"Error saving preferred quality", 2000)

    @pyqtSlot(str)
    def _on_aac_type_changed(self, aac_type: str):
        
        try:
            with open('config.yaml', 'r') as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}
        
        if config.get('aac-type') != aac_type:
            config['aac-type'] = aac_type
            try:
                with open('config.yaml', 'w') as f:
                    yaml.dump(config, f, sort_keys=False, allow_unicode=True)
                self.statusBar().showMessage(f"AAC type set to {aac_type}", 2000)
            except Exception as e:
                logging.error(f"Failed to save AAC type to config.yaml: {e}")
                self.statusBar().showMessage(f"Error saving AAC type", 2000)

    @pyqtSlot(dict)
    def on_settings_applied(self, config):
        current_sf = getattr(self.controller, 'storefront', '').lower()
        new_sf = (config.get('storefront') or '').lower()
        
        storefront_has_changed = new_sf and new_sf != current_sf and current_sf

        self.controller.apply_runtime_settings(config)

        if storefront_has_changed:
            logging.info(f"Storefront changed from '{current_sf}' to '{new_sf}'. Restart is required.")
            self._show_restart_popup()
        else:
    
            if self.current_query:
                self._execute_search(self.current_query)

    @pyqtSlot(int, str, float, float)
    def update_job_progress(self, job_id, status_text, track_percent, overall_percent):
        widget = self.queue_panel.get_job_widget(job_id)
        if widget:
            widget.update_progress(status_text, track_percent, overall_percent)

    @pyqtSlot(object)
    def on_card_download_requested(self, card_obj):
        if not hasattr(card_obj, "result_data"):
            return

        self._set_active_card(card_obj)
        data = getattr(card_obj, "result_data", None)
        
        if not data:
            self._clear_active_card()
            return

        url = data.get("appleMusicUrl")
        if not url:
            self.controller.update_status_and_log("Result has no valid URL.", "error")
            self._clear_active_card()
            return

        self.job_counter += 1
        job_id = self.job_counter
        
        if not hasattr(self, '_pending_song_by_job'):
            self._pending_song_by_job = {}

        item_type = data.get("type")
        if item_type == "songs":
            self._pending_song_by_job[job_id] = data.get('id')
        
        self.statusBar().showMessage(f"Fetching... for '{data.get('name', 'item')}'...", 3000)
        self.controller.fetch_media_for_download(url, job_id)

    @pyqtSlot(object)
    def on_search_result_clicked(self, card_obj):
        if not hasattr(card_obj, "result_data"):
            logging.error(f"Unexpected payload type for on_search_result_clicked: {type(card_obj)}")
            return

        self._set_active_card(card_obj)
        data = getattr(card_obj, "result_data", None)

        if not isinstance(data, dict):
            logging.error("Clicked payload missing data dict")
            self._clear_active_card()
            return

        item_type = data.get("type")
        if item_type == "artists":
            artist_page = ArtistDiscographyPage(self.controller, data)
            artist_page.back_requested.connect(self._navigate_back)
            artist_page.download_requested.connect(self.on_artist_page_download_requested)
            artist_page.tracklist_requested.connect(self.on_tracklist_requested)
            artist_page.info_requested.connect(self.on_info_requested)
            self.discography_batch_progress.connect(artist_page.on_discography_batch_progress)
            self.discography_batch_finished.connect(artist_page.on_discography_batch_finished)
            self.page_stack.addWidget(artist_page)
            self.page_stack.setCurrentWidget(artist_page)
            self._clear_active_card()

    @pyqtSlot()
    def _navigate_back(self):
        if self.page_stack.count() > 1 and hasattr(self, 'search_results_page'):
            page_to_remove = self.page_stack.currentWidget()
            if isinstance(page_to_remove, ArtistDiscographyPage):
                try:
                    self.discography_batch_progress.disconnect(page_to_remove.on_discography_batch_progress)
                    self.discography_batch_finished.disconnect(page_to_remove.on_discography_batch_finished)
                except TypeError:
                    pass
            self.page_stack.setCurrentWidget(self.search_results_page)
            self.page_stack.removeWidget(page_to_remove)
            page_to_remove.deleteLater()

    @pyqtSlot(list)
    def on_artist_page_download_requested(self, items_data: list):
        if isinstance(items_data, list):
            self._handle_discography_download(items_data)
        else:
            logging.error(f"Unexpected payload type for artist page download: {type(items_data)}")

    def _handle_discography_download(self, items: list):
        if not items:
            return
            
        self._disco_batch = {'total': len(items), 'done': 0}
        self.statusBar().showMessage(f"Fetching... for {len(items)} releases...", 3000)
        
        for item_data in items:
            url = item_data.get('appleMusicUrl')
            if not url:
                if self._disco_batch:
                    self._disco_batch['done'] += 1
                continue
            
            self.job_counter += 1
            job_id = self.job_counter
            self.controller.fetch_media_for_download(url, job_id)

    @pyqtSlot(dict)
    def on_discography_tracklist_requested(self, data: dict):
        self._clear_active_card()
        url = data.get('appleMusicUrl')
        if url:
            self.controller.fetch_media_for_track_selection(url)

    @pyqtSlot(dict)
    def open_track_listing_dialog(self, media_data):
        dialog = TrackListingDialog(media_data, self)
        self._clear_active_card()
        dialog.exec()

    @pyqtSlot(object)
    def on_tracklist_requested(self, card_obj):
        if not hasattr(card_obj, "result_data"):
            logging.error(f"Unexpected payload type for on_tracklist_requested: {type(card_obj)}")
            return
        
        self._set_active_card(card_obj)
        data = getattr(card_obj, "result_data", None)
        
        if data and (url := data.get('appleMusicUrl') or data.get('attributes', {}).get('url')):
            self.controller.fetch_media_for_track_selection(url)

    @pyqtSlot(object)
    def on_video_preview_requested(self, card):
        if card and hasattr(card, 'result_data'):
            self._set_active_card(card)
            self.controller.fetch_video_for_preview(card.result_data)

    @pyqtSlot(dict)
    def on_video_details_for_preview_loaded(self, video_data):
        self._clear_active_card()
        if video_data:
            dialog = VideoPreviewDialog(video_data, self)
            dialog.exec()

    @pyqtSlot(object)
    def on_info_requested(self, card_obj):
        if not hasattr(card_obj, "result_data"):
            logging.error(f"Unexpected payload type for on_info_requested: {type(card_obj)}")
            return

        self._set_active_card(card_obj)
        item_data = getattr(card_obj, "result_data", None)

        if not item_data:
            return

        item_type = item_data.get("type")

        if item_type == 'albums':
            url = item_data.get("appleMusicUrl") or item_data.get('attributes', {}).get('url')
            tracks = item_data.get("tracks_data") or []
            
            needs_refetch = (not tracks) or any(
                not t.get("attributes", {}).get("sampleRateHz") or
                not t.get("attributes", {}).get("bitDepth")
                for t in tracks
            )

            if needs_refetch and url:
                self.controller.album_details_for_info_loaded.connect(
                    self.open_album_info_dialog, Qt.ConnectionType.SingleShotConnection
                )
                self.controller.fetch_album_for_info(url)
            else:
                self.open_album_info_dialog(item_data)
        elif item_type == 'songs':
            self.controller.fetch_song_for_info(item_data)
        else:
            self.open_album_info_dialog(item_data)

    @pyqtSlot(dict)
    def open_album_info_dialog(self, item_data: dict):
        if self._info_dialog_open:
            return
        
        if not item_data:
            self._clear_active_card()
            return
        
        self._info_dialog_open = True
        dialog = InfoDialog(item_data, self)

        if (item_data.get("type") == "songs"):
            if (lay := dialog.layout()) is not None:
                lay.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        dialog.finished.connect(lambda: setattr(self, '_info_dialog_open', False))
        dialog.link_copied.connect(lambda: self.statusBar().showMessage("Link copied to clipboard!", 2000))
        self._clear_active_card()
        dialog.exec()

    @pyqtSlot(dict)
    def on_copy_link_requested(self, item_data: dict):
        """Copy Apple Music link to clipboard."""
        link = item_data.get('appleMusicUrl', '')
        if not link:
            self.statusBar().showMessage("No link available", 2000)
            return
        
        clipboard = QApplication.clipboard()
        clipboard.setText(link)
        self.statusBar().showMessage("Link copied to clipboard!", 2000)

    @pyqtSlot(dict)
    def on_lyrics_download_requested(self, item_data: dict):
        """Request lyrics download for an item."""
        item_id = item_data.get('id', '')
        item_name = item_data.get('name', 'Unknown')
        
        self._show_download_spinner(item_id)
        
        self.statusBar().showMessage(f"Fetching lyrics for {item_name}...", 3000)
        self.controller.download_lyrics(item_data)

    @pyqtSlot(dict)
    def on_artwork_download_requested(self, item_data: dict):
        """Request artwork download for an item."""
        item_id = item_data.get('id', '')
        item_name = item_data.get('name', 'Unknown')
        
        self._show_download_spinner(item_id)
        
        self.statusBar().showMessage(f"Fetching artwork for {item_name}...", 3000)
        self.controller.download_artwork(item_data)

    def _show_download_spinner(self, item_id: str):
        """Show loading spinner on cards for this item"""
        for url, card_set in self.card_widgets.items():
            for card_ref in list(card_set):
                if card_ref and not sip.isdeleted(card_ref):
                    if hasattr(card_ref, 'result_data') and card_ref.result_data.get('id') == item_id:
                        if hasattr(card_ref, 'download_button') and hasattr(card_ref.download_button, 'setState'):
                            card_ref.download_button.setState(card_ref.download_button.State.Loading)

    def _hide_download_spinner(self, item_id: str):
        """Hide loading spinner on cards for this item"""
        for url, card_set in self.card_widgets.items():
            for card_ref in list(card_set):
                if card_ref and not sip.isdeleted(card_ref):
                    if hasattr(card_ref, 'result_data') and card_ref.result_data.get('id') == item_id:
                        if hasattr(card_ref, 'download_button') and hasattr(card_ref.download_button, 'setState'):
                            card_ref.download_button.setState(card_ref.download_button.State.Idle)

    @pyqtSlot(str, bool, str)
    def on_lyrics_content_ready_for_save(self, item_id: str, success: bool, data_or_error: str):
        """Handle lyrics download completion for search cards, which require a save dialog."""
        self._hide_download_spinner(item_id)
        
        if not success:
            self.statusBar().showMessage(f"Lyrics download failed: {data_or_error}", 5000)
            return
        
        config = {}
        try:
            with open("config.yaml", "r") as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        
        item_data = self._get_item_data_by_id(item_id)
        if not item_data:
            default_filename = "lyrics"
        else:
            default_filename = self._format_filename_for_item(item_data, config)
        
        last_dir = config.get("last_lyrics_dir", os.path.expanduser("~/Music"))
        lrc_format = config.get("lrc-format", "lrc")
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Lyrics",
            os.path.join(last_dir, f"{default_filename}.{lrc_format}"),
            f"Lyrics Files (*.{lrc_format})"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(data_or_error)
                
                config["last_lyrics_dir"] = os.path.dirname(file_path)
                with open("config.yaml", "w") as f:
                    yaml.dump(config, f, sort_keys=False, allow_unicode=True)
                
                self.statusBar().showMessage(f"Lyrics saved to {os.path.basename(file_path)}", 3000)
            except Exception as e:
                self.statusBar().showMessage(f"Failed to save lyrics: {e}", 5000)

    @pyqtSlot(str, bool, str)
    def on_artwork_download_finished(self, item_id: str, success: bool, data_or_error: str):
    
        self._hide_download_spinner(item_id)
        
        if not success:
            self.statusBar().showMessage(f"Artwork download failed: {data_or_error}", 5000)
            return
        
        config = {}
        try:
            with open("config.yaml", "r") as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        
        item_data = self._get_item_data_by_id(item_id)
        if not item_data:
            default_filename = "cover"
        else:
            default_filename = "cover"
        
        last_dir = config.get("last_artwork_dir", os.path.expanduser("~/Pictures"))
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Artwork",
            os.path.join(last_dir, f"{default_filename}.jpg"),
            "Image Files (*.jpg *.png)"
        )
        
        if file_path:
            try:
                artwork_bytes = data_or_error.encode('latin1')
                
                with open(file_path, 'wb') as f:
                    f.write(artwork_bytes)
                
                config["last_artwork_dir"] = os.path.dirname(file_path)
                with open("config.yaml", "w") as f:
                    yaml.dump(config, f, sort_keys=False, allow_unicode=True)
                
                self.statusBar().showMessage(f"Artwork saved to {os.path.basename(file_path)}", 3000)
            except Exception as e:
                self.statusBar().showMessage(f"Failed to save artwork: {e}", 5000)

    def _get_item_data_by_id(self, item_id: str):
        """Find item data from card_widgets by ID"""
        for url, card_set in self.card_widgets.items():
            for card_ref in list(card_set):
                if card_ref and not sip.isdeleted(card_ref):
                    if hasattr(card_ref, 'result_data') and card_ref.result_data.get('id') == item_id:
                        return card_ref.result_data
        return None

    def _format_filename_for_item(self, item_data: dict, config: dict) -> str:
        """
        Format filename using song-file-format from config.
        Same logic as backend uses for actual downloads.
        """
        format_pattern = config.get("song-file-format", "{SongNumber}. {SongName}")
        
        song_name = item_data.get('name', 'Unknown')
        
        replacements = {
            '{SongId}': item_data.get('id', ''),
            '{SongNumber}': '',
            '{SongName}': song_name,
            '{DiscNumber}': '',
            '{TrackNumber}': '',
            '{Quality}': '',
            '{Codec}': '',
            '{Tag}': '',
        }
        
        filename = format_pattern
        for placeholder, value in replacements.items():
            filename = filename.replace(placeholder, value)
        
        filename = self._sanitize_filename(filename)
        
        return filename

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '')
        
        filename = filename.strip('. ')
        
        filename = ' '.join(filename.split())
        
        if not filename:
            filename = 'file'
        
        return filename

    @pyqtSlot(list)
    def on_track_qualities_loaded(self, updated_tracks: list):
        if self.track_selection_dialog and not sip.isdeleted(self.track_selection_dialog):
            self.track_selection_dialog.update_track_qualities(updated_tracks)

    @pyqtSlot(dict)
    def open_track_selection_dialog(self, media_data):
        self.track_selection_dialog = TrackSelectionDialog(media_data, self)
        self.track_selection_dialog.play_requested.connect(self.on_play_requested)
        self.track_selection_dialog.check_qualities_requested.connect(self.controller.fetch_qualities_for_dialog)
        self.controller.track_qualities_loaded.connect(self.track_selection_dialog.update_track_qualities)
        self._clear_active_card()
        
        result = self.track_selection_dialog.exec()
        
        
        try:
            self.controller.track_qualities_loaded.disconnect(self.track_selection_dialog.update_track_qualities)
        except TypeError:
            pass 

        selected_ids = self.track_selection_dialog.get_selected_track_ids()
        self.track_selection_dialog = None
        
        if result:
            if not selected_ids:
                return
            
            original_tracks = media_data.get('tracks', [])

            for track_id in selected_ids:
                selected_track_obj = next((t for t in original_tracks if t.get('trackData', {}).get('id') == track_id), None)
                
                if not selected_track_obj:
                    continue

                track_url = selected_track_obj.get('trackData', {}).get('attributes', {}).get('url')
                if not track_url:
                    self.controller.update_status_and_log(f"Could not find URL for track ID {track_id}. Skipping.", "error")
                    continue

                self.job_counter += 1
                job_id = self.job_counter
                
                track_specific_media_data = copy.deepcopy(media_data)
                final_media_data = self._prepare_job_data(track_specific_media_data, song_id=track_id)
                
                self._trigger_download(job_id, final_media_data, track_url)

    @pyqtSlot(int, int, int)
    def on_media_fetch_progress(self, job_id, current, total):
        self.statusBar().showMessage(f"Fetching... ({current}/{total})")
        if total > 0:
            self.fetch_progress_popup.setText(f"Fetching... ({current} / {total})")
            self._position_fetch_popup()
            self.fetch_progress_popup.show()

    @pyqtSlot(int, dict, str)
    def on_media_details_loaded(self, job_id, media_data, original_url):
        self._hide_link_spinner()
        
        song_id_for_job = self._pending_song_by_job.pop(job_id, None)
        final_media_data = self._prepare_job_data(media_data, song_id=song_id_for_job)
        
        if job_id in self.queue_panel.jobs:
            job_widget = self.queue_panel.jobs[job_id]
            job_widget.set_info(final_media_data)
            if job_widget.job_progress_bar.maximum() == 0:
                job_widget.job_progress_bar.setRange(0, 1000)
            job_widget.status_label.setText("Queued...")
        
        if self._disco_batch:
            self._disco_batch['done'] += 1
            done, total = self._disco_batch['done'], self._disco_batch['total']
            self.statusBar().showMessage(f"Fetched metadata for {done}/{total} releases.", 2000)
            self.discography_batch_progress.emit(done, total)
            if done >= total:
                self.statusBar().showMessage(f"Finished fetching metadata for all {total} releases.", 3000)
                self.discography_batch_finished.emit(total)
                self._disco_batch = None
        
        if self.fetch_progress_popup.isVisible():
            done_count = self._disco_batch['done'] if self._disco_batch else 1
            total_count = self._disco_batch['total'] if self._disco_batch else 1
            
            if done_count >= total_count:
                self.fetch_progress_popup.setText("Fetch Complete!")
                self._position_fetch_popup()
                QTimer.singleShot(2000, self.fetch_progress_popup.hide)
            else:
                self.fetch_progress_popup.setText(f"Fetching... ({done_count} / {total_count})")
                self._position_fetch_popup()

        if job_id > 0:
            self._trigger_download(job_id, final_media_data, original_url)
        else:
            logging.warning(f"on_media_details_loaded received job with no ID. This should not happen.")
            self.job_counter += 1
            new_job_id = self.job_counter
            self._trigger_download(new_job_id, final_media_data, original_url)

    def _prepare_job_data(self, media_data, song_id=None):

        if not song_id or 'tracks' not in media_data:
            return media_data

        original_tracks = media_data.get('tracks', [])
        selected_track_obj = next((t for t in original_tracks if t.get('trackData', {}).get('id') == song_id), None)

        if selected_track_obj:
            job_media_data = {
                'albumData': copy.deepcopy(media_data.get('albumData', {})),
                'tracks': [copy.deepcopy(selected_track_obj)]
            }
         
            job_media_data['_is_single_song'] = True
            
         
            album_attrs = job_media_data['albumData'].setdefault('attributes', {})
            track_attrs = selected_track_obj.get('trackData', {}).get('attributes', {})
            if 'audioTraits' in track_attrs:
                album_attrs['audioTraits'] = track_attrs['audioTraits']
            
            return job_media_data
        
        return media_data

    def _trigger_download(self, job_id, media_data, original_url):
        display_label = self.quality_selector.currentLabel() or ""
        self.queue_panel.add_job(job_id, media_data, display_label)
        
        label_lower = display_label.lower()
        quality_pref = "ALAC"
        if "atmos" in label_lower: quality_pref = "ATMOS"
        elif "aac" in label_lower: quality_pref = "AAC"
        
        is_song_url = ("/song/" in original_url) or re.search(r'[?&]i=\d+', original_url)
        
   
        url_to_download = media_data.get('albumData', {}).get('attributes', {}).get('url', original_url)
        

        if media_data.get('_is_single_song', False) or is_song_url:
            url_to_download = original_url
        
        self.trigger_download_job.emit(job_id, media_data, quality_pref, url_to_download)
        self._clear_active_card()

    def _is_decryptor_connection_error(self, msg: str) -> bool:
        if not msg:
            return False
        m = msg.lower()
        return ("failed to run v2" in m) or ("127.0.0.1:10020" in m) or ("actively refused" in m)

    @pyqtSlot(int, str)
    def _maybe_show_decryptor_popup(self, job_id: int, line: str):
        """Show a single app-modal wrapper error dialog, centered on the main window."""
        import time as _time
        lower = (line or "").lower()

        is_port_refused = ("127.0.0.1:10020" in lower) and (
            "refused" in lower or "connection refused" in lower or "actively refused" in lower
        )
        is_wrapper_common = ("invalid ckc" in lower) or ("playback error" in lower)
        if not (is_port_refused or is_wrapper_common):
            return

    
        now = _time.monotonic()
        if now - getattr(self, "_last_wrapper_popup_ts", 0) < 2:
            return
        self._last_wrapper_popup_ts = now

        excerpt = (line or "").strip()
        if len(excerpt) > 160:
            excerpt = excerpt[:157] + "..."

  
        try:
            if self._wrapper_popup and self._wrapper_popup.isVisible():
                self._wrapper_popup.raise_()
                self._wrapper_popup.activateWindow()
                return
        except Exception:
            pass

        self._wrapper_popup = WrapperErrorDialog(error_excerpt=excerpt, parent=self)
        try:
            rect = self.geometry()
            self._wrapper_popup.move(rect.center() - self._wrapper_popup.rect().center())
        except Exception:
            pass

      
        self._wrapper_popup.exec()
        
    @pyqtSlot(str)
    def on_search_failed(self, error_message):
        """Handles failures during a text-based search."""
        logging.error(f"Search failed: {error_message}")
        self._hide_link_spinner()
        
        if "/v1/catalog//" in error_message and "400" in error_message:
            self.show_storefront_required_dialog()
        else:
            self.show_popup(f"Search failed: {error_message}")

    @pyqtSlot(int, str, str)
    def on_media_fetch_failed(self, job_id, url, error_message):
        self._hide_link_spinner()
        self._clear_active_card()
        self.fetch_progress_popup.hide()
        
        if "/v1/catalog//" in error_message and "400" in error_message:
            self.show_storefront_required_dialog()
            return

        if self._is_decryptor_connection_error(error_message):
            self.show_popup(f"{error_message}\n\nMAKE SURE WRAPPER IS CONNECTED OR RUNNING PROPERLY.")
        else:
            self.show_popup(f"Failed to fetch details for {url}: {error_message}")
        
        if self._disco_batch:
            self._disco_batch['done'] += 1
            done, total = self._disco_batch['done'], self._disco_batch['total']
            if done >= total:
                self.statusBar().showMessage(f"Finished fetching metadata for all {total} releases.", 3000)
                self.discography_batch_finished.emit(total)
                self._disco_batch = None
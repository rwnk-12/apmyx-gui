from PyQt6 import sip
from PyQt6.QtCore import pyqtSlot

class SelectionFeatures:
    """Features for managing selection of items for batch download."""

    def show_selection_dropdown(self):
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.close()
            return
        self.selection_dropdown.update_items(self.selection_manager)
        self.selection_dropdown.show_under(self.live_queue_button)

    def _update_selection_controls(self):
        count = len(self.selection_manager)
        
        self.selection_controls_widget.setVisible(count > 0)
        self.download_selected_button.setText(f"Download Selected ({count})")

    def _clear_selection(self):
        urls_to_clear = list(self.selection_manager.keys())
        if not urls_to_clear:
            return

        for url in urls_to_clear:
            self._remove_single_selection(url, update_controls=False)
        
        self._update_selection_controls()

    @pyqtSlot(str)
    def _remove_single_selection(self, item_url: str, update_controls=True):
        if item_url in self.card_widgets:

            for card in list(self.card_widgets[item_url]):
                if card and not sip.isdeleted(card):
                    try:
                        card.setSelected(False)
                    except RuntimeError:
                        pass  
        else:
   
            self.selection_manager.pop(item_url, None)
            if update_controls:
                self._update_selection_controls()

    @pyqtSlot(list)
    def _on_clear_selected_requested(self, urls_to_clear: list):
        if not urls_to_clear:
            return

        for url in urls_to_clear:
            self._remove_single_selection(url, update_controls=False)

        self._update_selection_controls()
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.update_items(self.selection_manager)

    @pyqtSlot(dict, bool)
    def _handle_selection_toggled(self, item_data, is_selected):
        item_url = item_data.get('appleMusicUrl')
        if not item_url:
            return
        
        if is_selected:
            self.selection_manager[item_url] = item_data
        else:
            self.selection_manager.pop(item_url, None)
            
        self._update_selection_controls()
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.update_items(self.selection_manager)

    def _on_download_selected_clicked(self):
        if not self.selection_manager:
            return
            
        items_to_download = list(self.selection_manager.values())
        self.statusBar().showMessage(f"Adding {len(items_to_download)} items to queue...", 3000)
        
        if not hasattr(self, '_pending_song_by_job'):
            self._pending_song_by_job = {}

        for item_data in items_to_download:
            url = item_data.get('appleMusicUrl')
            if not url: continue

            self.job_counter += 1
            job_id = self.job_counter
            
            item_type = item_data.get("type")
            if item_type == "songs":
                self._pending_song_by_job[job_id] = item_data.get('id')
            
            self.statusBar().showMessage(f"Fetching details for '{item_data.get('name', 'item')}'...", 3000)
            self.controller.fetch_media_for_download(url, job_id)
        
        self._clear_selection()
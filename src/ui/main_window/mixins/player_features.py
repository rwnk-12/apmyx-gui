from PyQt6 import sip
from PyQt6.QtCore import pyqtSlot, QTimer
from ...preview_player import Player
from ...search_cards import PlayButton
import weakref
import logging

class PlayerFeatures:
    """Features for handling media player interactions."""

    @pyqtSlot()
    def on_player_bar_close_requested(self):
        logging.debug("Player bar close requested, stopping player.")
        self.player.stop()
        self.player_bar.hide()

    @pyqtSlot(dict)
    def on_play_requested(self, track_data):
        self.player.play(track_data)

    @pyqtSlot()
    def on_player_bar_play_toggled(self):
        if self.player.current_track_data:
            self.player.play(self.player.current_track_data)

    @pyqtSlot(dict)
    def on_player_track_changed(self, track_data):
        self.player_bar.set_track(track_data)
        self.player_bar.show()

    @pyqtSlot(int, str)
    def on_player_state_changed(self, state, song_url):
        button_state = self.player_state_to_button_state.get(state, PlayButton.State.Stopped)
        self.player_bar.set_playback_state(button_state)

        if self.track_selection_dialog and not sip.isdeleted(self.track_selection_dialog):
            self.track_selection_dialog.update_playback_state(button_state, song_url)

        if state == Player.StoppedState:
            self.player_bar.update_progress(0, 0)

        if self.active_playback_card_url and self.active_playback_card_url != song_url:
            card_set = self.card_widgets.get(self.active_playback_card_url, weakref.WeakSet())
            for old_card in card_set:
                if old_card:
                    try:
                        if hasattr(old_card, 'set_playback_state'):
                            old_card.set_playback_state(PlayButton.State.Stopped)
                    except RuntimeError:
                        pass

        card_set = self.card_widgets.get(song_url, weakref.WeakSet())
        for new_card in card_set:
            if new_card:
                try:
                    if hasattr(new_card, 'set_playback_state'):
                        new_card.set_playback_state(button_state)
                except RuntimeError:
                    pass

        if state == Player.StoppedState:
            self.active_playback_card_url = None
            QTimer.singleShot(2000, self._hide_player_if_stopped)
        else:
            self.active_playback_card_url = song_url

    def _hide_player_if_stopped(self):
        if self.player.current_state == Player.StoppedState:
            self.player_bar.hide()
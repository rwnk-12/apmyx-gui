import re
import logging
import weakref
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QHBoxLayout
)
from PyQt6.QtCore import Qt, QTimer, QByteArray
from PyQt6.QtGui import QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
from ...search_widgets import LoadingSpinner
from ...search_cards import SearchResultCard, SongListCard
from ..utility_widgets import ListLoadingIndicator

class SearchFeatures:
    def _ensure_storefront_or_prompt(self) -> bool:
        sf = getattr(self.controller, "storefront", "") or ""
        if not sf.strip():
            self.show_storefront_required_dialog()
            return False
        return True

    def handle_input(self):
        if not self._ensure_storefront_or_prompt():
            return
        text = self.search_input.text().strip()
        if not text:
            return
        if "music.apple.com" in text:
            self._handle_url_paste(text)
        else:
            self.on_search_clicked()

    def _handle_url_paste(self, text: str):
        if not self._ensure_storefront_or_prompt():
            return
        self._show_link_spinner()
        match = re.search(r'(https://music\.apple\.com/[^&]+)', text)
        if match:
            clean_url = match.group(1)
            self.search_input.line_edit.clear()
            self.job_counter += 1
            job_id = self.job_counter
            song_id_match = re.search(r'[?&]i=(\d+)', clean_url)
            if not song_id_match:
                song_id_match = re.search(r'/song/[^/]+/(\d+)', clean_url)
            if song_id_match:
                song_id = song_id_match.group(1)
                self._pending_song_by_job[job_id] = song_id
                logging.info(f"Detected single song paste. Job ID: {job_id}, Song ID: {song_id}")
            self.controller.fetch_media_for_download(clean_url, job_id)
        else:
            self.show_popup("Invalid or malformed Apple Music URL.")
            self._hide_link_spinner()

    def on_scroll(self, value, category):
        if self.is_initial_loading.get(category):
            return
        if self.is_loading_more.get(category) or self.no_more_results.get(category):
            return
        scrollbar = self.scroll_areas[category].verticalScrollBar()
        if value >= scrollbar.maximum() - 150:
            self.is_loading_more[category] = True
            container = self.tab_containers.get(category)
            if container:
                layout = container.layout()
                if category == 'songs' and self.songs_view_mode == 'list':
                    if isinstance(layout, QVBoxLayout):
                        self.list_loading_indicator = ListLoadingIndicator(container)
                        layout.addWidget(self.list_loading_indicator)
                elif isinstance(layout, QGridLayout):
                    item_count = layout.count()
                    cols = max(1, self.main_content_container.width() // 200)
                    next_row = item_count // cols
                    next_col = item_count % cols
                    if self.loading_tile.parent() is None:
                        layout.addWidget(self.loading_tile, next_row, next_col)
                    self.loading_tile.show()
                    self.loading_tile.start()
            offset = self.search_offsets.get(category, 0) + 30
            self.search_offsets[category] = offset
            self.controller.load_more_results(self.current_query, category, offset)

    def on_search_clicked(self):
        if not self._ensure_storefront_or_prompt():
            return
        query = self.search_input.text().strip()
        if not query: return
        if self._is_panel_animating:
            QTimer.singleShot(300, lambda: self._execute_search(query))
        else:
            self._execute_search(query)

    def _execute_search(self, query):
        if hasattr(self, 'search_results_page') and self.page_stack.currentWidget() != self.search_results_page:
            self._navigate_back()
        self._clear_selection()
        self.current_query = query
        self.search_cache = {}
        self.search_offsets = {'songs': 0, 'albums': 0, 'artists': 0, 'music_videos': 0, 'playlists': 0}
        self.is_loading_more = {'songs': False, 'albums': False, 'artists': False, 'music_videos': False, 'playlists': False}
        self.is_initial_loading = {'songs': True, 'albums': True, 'artists': True, 'music_videos': True, 'playlists': True, 'top_results': True}
        self.no_more_results = {'songs': False, 'albums': False, 'artists': False, 'music_videos': False, 'playlists': False}
        self.albums_tab_searched = False
        self.music_videos_tab_searched = False
        self.playlists_tab_searched = False
        for key, spinner in self.loading_spinners.items():
            if spinner and not sip.isdeleted(spinner):
                spinner.stop()
                spinner.deleteLater()
        self.loading_spinners.clear()
        for container in self.tab_containers.values():
            if container is self.tab_containers['top_results']:
                self._clear_layout(self.top_results_content_widget.layout())
            else:
                self._clear_layout(container.layout())
        container = self.top_results_content_widget
        layout = QVBoxLayout(container)
        spinner = LoadingSpinner(container)
        spinner.setFixedSize(50, 50)
        layout.addWidget(spinner, 0, Qt.AlignmentFlag.AlignCenter)
        spinner.start()
        self.loading_spinners['top_results'] = spinner
        self.tab_containers['top_results'].layout().setCurrentWidget(self.top_results_content_widget)
        self.tab_widget.setCurrentIndex(0)
        self.controller.search(query)

    def on_tab_changed(self, index):
        tab_text = self.tab_widget.tabText(index)
        if tab_text == "Albums" and not self.albums_tab_searched:
            self.albums_tab_searched = True
            container = self.tab_containers['albums']
            self._clear_layout(container.layout())
            layout = QVBoxLayout(container)
            spinner = LoadingSpinner(container)
            spinner.setFixedSize(50, 50)
            layout.addWidget(spinner, 0, Qt.AlignmentFlag.AlignCenter)
            spinner.start()
            self.loading_spinners['albums'] = spinner
            self.controller.search_for_albums(self.current_query)
        elif tab_text == "Music Videos" and not self.music_videos_tab_searched:
            self.music_videos_tab_searched = True
            container = self.tab_containers['music_videos']
            self._clear_layout(container.layout())
            layout = QVBoxLayout(container)
            spinner = LoadingSpinner(container)
            spinner.setFixedSize(50, 50)
            layout.addWidget(spinner, 0, Qt.AlignmentFlag.AlignCenter)
            spinner.start()
            self.loading_spinners['music_videos'] = spinner
            self.controller.search_for_music_videos(self.current_query)
        elif tab_text == "Playlists" and not self.playlists_tab_searched:
            self.playlists_tab_searched = True
            container = self.tab_containers['playlists']
            self._clear_layout(container.layout())
            layout = QVBoxLayout(container)
            spinner = LoadingSpinner(container)
            spinner.setFixedSize(50, 50)
            layout.addWidget(spinner, 0, Qt.AlignmentFlag.AlignCenter)
            spinner.start()
            self.loading_spinners['playlists'] = spinner
            self.controller.search_for_playlists(self.current_query)
        self._update_view_toggle_button()

    def _populate_top_results_tab(self, results):
        container = self.top_results_content_widget
        self._clear_layout(container.layout())
        if not any(results.values()):
            self.tab_containers['top_results'].layout().setCurrentWidget(self.search_placeholder_widget)
            return
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        self._add_results_section(layout, "Top Results", results.get('top_results', []), SearchResultCard, 'grid', 6)
        self._add_results_section(layout, "Songs", results.get('songs', []), SongListCard, 'grid_list', 8, card_init_kwargs={})
        self._add_results_section(layout, "Albums", results.get('albums', []), SearchResultCard, 'grid', 6)
        self._add_results_section(layout, "Artists", results.get('artists', []), SearchResultCard, 'grid', 6)
        self._add_results_section(layout, "Music Videos", results.get('music_videos', []), SearchResultCard, 'grid', 6)
        self._add_results_section(layout, "Playlists", results.get('playlists', []), SearchResultCard, "grid", 6)
        layout.addStretch()

    def _add_results_section(self, parent_layout, title, items, card_class, layout_type, item_limit=None, card_init_kwargs=None):
        if not items: 
            return
        
        if item_limit:
            items = items[:item_limit]
        
        tab_sections = ["Songs", "Albums", "Artists", "Music Videos", "Playlists"]
        
        if title in tab_sections:
            header_container = QWidget()
            header_layout = QHBoxLayout(header_container)
            header_layout.setContentsMargins(0, 10, 0, 5)
            header_layout.setSpacing(4)
            
            header = QLabel(title)
            header.setStyleSheet("font-size: 17px; font-weight: bold;")
            
            chevron_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#969696" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>'''
            
            chevron_label = QLabel()
            renderer = QSvgRenderer(QByteArray(chevron_svg.encode()))
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            chevron_label.setPixmap(pixmap)
            chevron_label.setFixedSize(16, 16)
            
            header_container.setCursor(Qt.CursorShape.PointingHandCursor)
            header_container.mousePressEvent = lambda event, t=title: self._navigate_to_tab(t)
            
            header_layout.addWidget(header, 0, Qt.AlignmentFlag.AlignVCenter)
            header_layout.addWidget(chevron_label, 0, Qt.AlignmentFlag.AlignVCenter)
            header_layout.addStretch()
            
            parent_layout.addWidget(header_container)
        else:
            header = QLabel(title)
            header.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
            parent_layout.addWidget(header)
        
        content_widget = QWidget()
        
        if layout_type == 'grid' or layout_type == 'grid_list':
            layout = QGridLayout(content_widget)
            layout.setProperty("reflowable", True)
            layout.setProperty("mode", layout_type)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            layout.setSpacing(4)
            cols = 2 if layout_type == 'grid_list' else max(1, self.main_content_container.width() // 200)
            
            for i, item in enumerate(items):
                card = card_class(item, **(card_init_kwargs or {}))
                item_url = item.get('appleMusicUrl')
                if item_url in self.selection_manager:
                    card.setSelected(True)
                if hasattr(card, 'clicked'): card.clicked.connect(self.on_search_result_clicked)
                if hasattr(card, 'download_requested'): card.download_requested.connect(self.on_card_download_requested)
                if hasattr(card, 'play_requested'): card.play_requested.connect(self.on_play_requested)
                if hasattr(card, 'selection_toggled'): card.selection_toggled.connect(self._handle_selection_toggled)
                if item_url:
                    if item_url not in self.card_widgets:
                        self.card_widgets[item_url] = weakref.WeakSet()
                    self.card_widgets[item_url].add(card)
                if hasattr(card, 'tracklist_requested'): card.tracklist_requested.connect(self.on_tracklist_requested)
                if hasattr(card, 'info_requested'): card.info_requested.connect(self.on_info_requested)
                if hasattr(card, 'link_copied'): card.link_copied.connect(lambda: self.statusBar().showMessage("Link copied to clipboard!", 2000))
                if hasattr(card, 'video_preview_requested'): card.video_preview_requested.connect(self.on_video_preview_requested)
                if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                layout.addWidget(card, i // cols, i % cols)
        else:
            layout = QVBoxLayout(content_widget)
            layout.setSpacing(2)
            for item in items:
                card = card_class(item, **(card_init_kwargs or {}))
                item_url = item.get('appleMusicUrl')
                if item_url in self.selection_manager:
                    card.setSelected(True)
                if hasattr(card, 'clicked'): card.clicked.connect(self.on_search_result_clicked)
                if hasattr(card, 'download_requested'): card.download_requested.connect(self.on_card_download_requested)
                if hasattr(card, 'play_requested'): card.play_requested.connect(self.on_play_requested)
                if hasattr(card, 'selection_toggled'): card.selection_toggled.connect(self._handle_selection_toggled)
                if item_url:
                    if item_url not in self.card_widgets:
                        self.card_widgets[item_url] = weakref.WeakSet()
                    self.card_widgets[item_url].add(card)
                if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                layout.addWidget(card)
        
        parent_layout.addWidget(content_widget)

    def _navigate_to_tab(self, section_title):
        tab_mapping = {
            "Songs": 1,
            "Albums": 2,
            "Artists": 3,
            "Music Videos": 4,
            "Playlists": 5
        }
        
        if section_title in tab_mapping:
            tab_index = tab_mapping[section_title]
            self.tab_widget.setCurrentIndex(tab_index)
            
            if section_title == "Albums" and not self.albums_tab_searched:
                self.on_tab_changed(tab_index)
            elif section_title == "Music Videos" and not self.music_videos_tab_searched:
                self.on_tab_changed(tab_index)
            elif section_title == "Playlists" and not self.playlists_tab_searched:
                self.on_tab_changed(tab_index)

    def _populate_category_tab(self, category, items):
        container = self.tab_containers[category]
        self._clear_layout(container.layout())
        layout = None
        
        if category == 'songs':
            if self.songs_view_mode == 'list':
                layout = QVBoxLayout(container)
                layout.setSpacing(0)
                layout.setContentsMargins(5, 0, 5, 0)
                for item in items:
                    card = SongListCard(item)
                    item_url = item.get('appleMusicUrl')
                    if item_url in self.selection_manager:
                        card.setSelected(True)
                    card.download_requested.connect(self.on_card_download_requested)
                    card.play_requested.connect(self.on_play_requested)
                    card.selection_toggled.connect(self._handle_selection_toggled)
                    card.info_requested.connect(self.on_info_requested)
                    if item_url:
                        if item_url not in self.card_widgets:
                            self.card_widgets[item_url] = weakref.WeakSet()
                        self.card_widgets[item_url].add(card)
                    if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                    if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                    if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                    layout.addWidget(card)
                layout.addStretch(1)
            else:
                layout = QGridLayout(container)
                layout.setProperty("reflowable", True)
                layout.setSpacing(10)
                cols = max(1, self.main_content_container.width() // 200)
                for i, item in enumerate(items):
                    card = SearchResultCard(item)
                    item_url = item.get('appleMusicUrl')
                    if item_url in self.selection_manager:
                        card.setSelected(True)
                    card.download_requested.connect(self.on_card_download_requested)
                    card.selection_toggled.connect(self._handle_selection_toggled)
                    if item_url:
                        if item_url not in self.card_widgets:
                            self.card_widgets[item_url] = weakref.WeakSet()
                        self.card_widgets[item_url].add(card)
                    card.info_requested.connect(self.on_info_requested)
                    card.link_copied.connect(lambda: self.statusBar().showMessage("Link copied to clipboard!", 2000))
                    if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                    if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                    if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                    layout.addWidget(card, i // cols, i % cols)
                row_count = (len(items) + cols - 1) // cols
                layout.setRowStretch(row_count, 1)
        else:
            layout = QGridLayout(container)
            layout.setProperty("reflowable", True)
            layout.setSpacing(10)
            cols = max(1, self.main_content_container.width() // 200)
            for i, item in enumerate(items):
                card = SearchResultCard(item)
                item_url = item.get('appleMusicUrl')
                if item_url in self.selection_manager:
                    card.setSelected(True)
                card.download_requested.connect(self.on_card_download_requested)
                card.clicked.connect(self.on_search_result_clicked)
                card.selection_toggled.connect(self._handle_selection_toggled)
                if item_url:
                    if item_url not in self.card_widgets:
                        self.card_widgets[item_url] = weakref.WeakSet()
                    self.card_widgets[item_url].add(card)
                card.tracklist_requested.connect(self.on_tracklist_requested)
                card.info_requested.connect(self.on_info_requested)
                card.link_copied.connect(lambda: self.statusBar().showMessage("Link copied to clipboard!", 2000))
                if hasattr(card, 'video_preview_requested'):
                    card.video_preview_requested.connect(self.on_video_preview_requested)
                if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                layout.addWidget(card, i // cols, i % cols)
            row_count = (len(items) + cols - 1) // cols
            layout.setRowStretch(row_count, 1)
        
        if not items and layout is not None:
            no_results_label = QLabel("No results in this category.")
            no_results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_results_label)

    def display_search_results(self, results: dict):
        spinner = self.loading_spinners.pop('top_results', None)
        if spinner and not sip.isdeleted(spinner):
            spinner.stop()
            spinner.deleteLater()
        self.search_cache = results
        self._populate_top_results_tab(results)
        self._populate_category_tab('songs', results.get('songs', []))
        self._populate_category_tab('artists', results.get('artists', []))
        
        if not self.albums_tab_searched:
            albums_container = self.tab_containers['albums']
            self._clear_layout(albums_container.layout())
            prompt_label = QLabel("Album results will be loaded when this tab is selected.")
            prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout = QVBoxLayout(albums_container)
            layout.addWidget(prompt_label)
        
        if not self.music_videos_tab_searched:
            videos_container = self.tab_containers['music_videos']
            self._clear_layout(videos_container.layout())
            prompt_label = QLabel("Music Video results will be loaded when this tab is selected.")
            prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout = QVBoxLayout(videos_container)
            layout.addWidget(prompt_label)
        
        if not self.playlists_tab_searched:
            playlists_container = self.tab_containers['playlists']
            self._clear_layout(playlists_container.layout())
            prompt_label = QLabel("Playlist results will be loaded when this tab is selected.")
            prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout = QVBoxLayout(playlists_container)
            layout.addWidget(prompt_label)
        
        self.is_initial_loading = {key: False for key in self.is_initial_loading}

    def handle_category_search_results(self, category, results):
        spinner = self.loading_spinners.pop(category, None)
        if spinner and not sip.isdeleted(spinner):
            spinner.stop()
            spinner.deleteLater()
        
        if category == 'albums':
            self.search_cache['albums'] = results
            self._populate_category_tab('albums', results)
            self.is_initial_loading['albums'] = False
        elif category == 'music_videos':
            self.search_cache['music_videos'] = results
            self._populate_category_tab('music_videos', results)
            self.is_initial_loading['music_videos'] = False
        elif category == 'playlists':
            self.search_cache['playlists'] = results
            self._populate_category_tab('playlists', results)
            self.is_initial_loading['playlists'] = False

    def append_search_results(self, category, new_items):
        self.loading_tile.stop()
        self.loading_tile.hide()
        self.loading_tile.setParent(None)
        
        if hasattr(self, 'list_loading_indicator') and self.list_loading_indicator:
            self.list_loading_indicator.setParent(None)
            self.list_loading_indicator.deleteLater()
            self.list_loading_indicator = None
        
        category_key = category.replace('-', '_')
        if not new_items:
            self.no_more_results[category_key] = True
        
        self.search_cache.setdefault(category_key, []).extend(new_items)
        self._start_append_chunk(category_key, new_items)

    def _start_append_chunk(self, category_key, items_to_add):
        if not items_to_add:
            self.is_loading_more[category_key] = False
            return
        
        chunk_size = 12
        chunk = items_to_add[:chunk_size]
        remaining = items_to_add[chunk_size:]
        
        self._perform_append_chunk(category_key, chunk)
        
        if remaining:
            QTimer.singleShot(50, lambda: self._start_append_chunk(category_key, remaining))
        else:
            self.is_loading_more[category_key] = False

    def _perform_append_chunk(self, category_key, new_items_chunk):
        container = self.tab_containers.get(category_key)
        if not container or not new_items_chunk:
            return
        
        container.setUpdatesEnabled(False)
        try:
            layout = container.layout()
            
            if category_key == 'songs' and self.songs_view_mode == 'list':
                if not isinstance(layout, QVBoxLayout):
                    logging.warning(f"Layout for 'songs' list view is not a QVBoxLayout. Cannot append.")
                    self.is_loading_more[category_key] = False
                    return
                
                if layout.count() > 0:
                    item = layout.itemAt(layout.count() - 1)
                    if item and item.spacerItem():
                        layout.removeItem(item)
                
                for item in new_items_chunk:
                    card = SongListCard(item)
                    item_url = item.get('appleMusicUrl')
                    if item_url in self.selection_manager:
                        card.setSelected(True)
                    card.download_requested.connect(self.on_card_download_requested)
                    card.play_requested.connect(self.on_play_requested)
                    card.selection_toggled.connect(self._handle_selection_toggled)
                    card.info_requested.connect(self.on_info_requested)
                    if item_url:
                        if item_url not in self.card_widgets:
                            self.card_widgets[item_url] = weakref.WeakSet()
                        self.card_widgets[item_url].add(card)
                    if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                    if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                    if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                    layout.addWidget(card)
                
                layout.addStretch(1)
                return
            
            if not isinstance(layout, QGridLayout):
                logging.warning(f"Layout for category '{category_key}' is not a QGridLayout. Cannot append more items.")
                self.is_loading_more[category_key] = False
                return
            
            cols = max(1, self.main_content_container.width() // 200)
            old_item_count = layout.count()
            
            if old_item_count > 0:
                last_row_with_stretch = (old_item_count + cols - 1) // cols
                layout.setRowStretch(last_row_with_stretch, 0)
            
            current_count = layout.count()
            card_class = SearchResultCard
            
            for i, item in enumerate(new_items_chunk):
                card = card_class(item)
                item_url = item.get('appleMusicUrl')
                if item_url in self.selection_manager:
                    card.setSelected(True)
                card.download_requested.connect(self.on_card_download_requested)
                if hasattr(card, 'clicked'): card.clicked.connect(self.on_search_result_clicked)
                card.selection_toggled.connect(self._handle_selection_toggled)
                if item_url:
                    if item_url not in self.card_widgets:
                        self.card_widgets[item_url] = weakref.WeakSet()
                    self.card_widgets[item_url].add(card)
                if hasattr(card, 'tracklist_requested'): card.tracklist_requested.connect(self.on_tracklist_requested)
                if hasattr(card, 'info_requested'): card.info_requested.connect(self.on_info_requested)
                if hasattr(card, 'link_copied'): card.link_copied.connect(lambda: self.statusBar().showMessage("Link copied to clipboard!", 2000))
                if hasattr(card, 'video_preview_requested'): card.video_preview_requested.connect(self.on_video_preview_requested)
                if hasattr(card, 'lyrics_download_requested'): card.lyrics_download_requested.connect(self.on_lyrics_download_requested)
                if hasattr(card, 'artwork_download_requested'): card.artwork_download_requested.connect(self.on_artwork_download_requested)
                if hasattr(card, 'copy_link_requested'): card.copy_link_requested.connect(self.on_copy_link_requested)
                total_index = current_count + i
                layout.addWidget(card, total_index // cols, total_index % cols)
            
            new_item_count = layout.count()
            if new_item_count > 0:
                new_row_count = (new_item_count + cols - 1) // cols
                layout.setRowStretch(new_row_count, 1)
        finally:
            if container:
                container.setUpdatesEnabled(True)

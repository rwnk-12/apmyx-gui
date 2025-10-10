from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QFrame, QTabWidget,
    QGraphicsOpacityEffect, QToolButton, QScroller,
    QScrollerProperties, QListView, QApplication, QStyle,
    QStyleOptionViewItem, QScrollArea, QGridLayout, QMessageBox
)
from PyQt6.QtCore import (
    pyqtSignal, pyqtSlot, QThreadPool, Qt, QTimer,
    QPropertyAnimation, QEasingCurve, QModelIndex, QSize, QPoint, QEvent
)
from PyQt6.QtGui import QFont, QPixmap, QFontMetrics, QCursor
from PyQt6 import sip
import weakref
import logging

from ..search_widgets import LoadingSpinner
from .artist_hero_and_header import ArtistHeroWidget, SegmentedTabs
from .artist_card import ArtistAlbumCard
from ..view_select import SelectionDropdown

class ArtistDiscographyPage(QWidget):
    back_requested = pyqtSignal()
    download_requested = pyqtSignal(list)
    tracklist_requested = pyqtSignal(object)
    info_requested = pyqtSignal(object)
    menu_requested = pyqtSignal()
    
    def __init__(self, controller, artist_data: dict, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.artist_data = artist_data
        
        self.selection_manager = {}
        self._is_downloading_all = False
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.hero = ArtistHeroWidget(artist_data, self)
        self.hero.back_requested.connect(self.back_requested.emit)
        self.hero.download_all_requested.connect(self._on_download_all_clicked)
        self.hero.menu_requested.connect(self.menu_requested.emit)
        self.hero.installEventFilter(self)
        self.main_layout.addWidget(self.hero)
        
        self.compact_bar = QFrame(self)
        self.compact_bar.setMinimumHeight(48)
        self.compact_bar.setStyleSheet("background-color: #1f1f1f; border-bottom: 1px solid #2c2c2c; padding: 5px;")
        c_lay = QHBoxLayout(self.compact_bar)
        c_lay.setContentsMargins(12, 4, 12, 4)
        c_lay.setSpacing(8)

        self.compact_back = QToolButton(self.compact_bar)
        self.compact_back.setAutoRaise(True)
        self.compact_back.setArrowType(Qt.ArrowType.LeftArrow)
        self.compact_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compact_back.clicked.connect(self.back_requested.emit)
        self.compact_back.setStyleSheet("QToolButton{color:#eaeaea;} QToolButton:hover{color:#ffffff;}")

        self.compact_name = QLabel(self.artist_data.get('name', ''))
        self.compact_name.setStyleSheet("color:#eaeaea; font-weight:700; font-size:14px;")
        self.compact_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.compact_dl = QPushButton("Download Discography", self.compact_bar)
        self.compact_dl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compact_dl.setFixedHeight(28)
        self.compact_dl.setStyleSheet(
            "font-weight:bold; padding:4px 12px; background-color:#B03400; border:none; border-radius:14px;"
        )
        self.compact_dl.clicked.connect(self._on_download_all_clicked)

        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.addWidget(self.compact_back)
        left_layout.addWidget(self.compact_name)
        left_layout.addStretch()

        c_lay.addWidget(left_container)
        c_lay.addStretch()
        c_lay.addWidget(self.compact_dl)

        self.compact_bar.setVisible(False)
        self.main_layout.insertWidget(1, self.compact_bar)
        QTimer.singleShot(0, self._elide_compact_title)
        
        self.categories = ["Albums", "EPs", "Singles", "Music Videos", "Compilations"]
        self.segmented_header = SegmentedTabs(self.categories, accent="#fd576b")
        self.main_layout.addWidget(self.segmented_header)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.tabBar().hide()
        self.main_layout.addWidget(self.tab_widget, 1)

        self.segmented_header.segmentChanged.connect(self.tab_widget.setCurrentIndex)
        self.tab_widget.currentChanged.connect(self.segmented_header.set_current_index)
        
        self.scroll_areas = {}
        self.grid_layouts = {}
        self.grid_containers = {}
        
        for cat in self.categories:
            self._create_tab(cat)
        
        self._add_bottom_controls()
        
        self.spinner = LoadingSpinner(self)
        self.spinner.setFixedSize(50, 50)
        self.spinner.hide()
        
        self.controller.artist_discography_loaded.connect(self.populate_album_list)

        self._hero_anim = QPropertyAnimation(self.hero, b"heroHeight", self)
        self._hero_anim.setDuration(170)
        self._hero_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        self.tab_widget.currentChanged.connect(self._connect_scroll_events)
        
        self.show_loading_state()

        main_window = self.window()
        if main_window and hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage(f"Fetching discography for {self.artist_data.get('name', 'artist')}...", 0)

        self.controller.resolve_artist(self.artist_data.get('appleMusicUrl'))

    def _get_current_view(self) -> QScrollArea | None:
        key = self.categories[self.tab_widget.currentIndex()].lower().replace(" ", "_")
        return self.scroll_areas.get(key)

    def eventFilter(self, obj, event):
        if obj is self.hero and event.type() == QEvent.Type.Wheel:
            if view := self._get_current_view():
                QApplication.sendEvent(view, event)
                return True
        return super().eventFilter(obj, event)

    def _elide_compact_title(self):
        try:
            fm = QFontMetrics(self.compact_name.font())
            full = self.artist_data.get('name', '')
            reserve = 180
            w = max(10, self.compact_bar.width() - reserve)
            self.compact_name.setText(fm.elidedText(full, Qt.TextElideMode.ElideRight, w))
        except Exception:
            pass

    def _connect_scroll_events(self):
        if view := self._get_current_view():
            sb = view.verticalScrollBar()
            try:
                sb.valueChanged.disconnect(self._on_scroll_value)
            except TypeError:
                pass
            sb.valueChanged.connect(self._on_scroll_value)
            self._on_scroll_value(sb.value())

    def _on_scroll_value(self, v: int):
        target_height = max(0, self.hero.expanded_height - v)
        
        if self._hero_anim.state() == QPropertyAnimation.State.Running:
            self._hero_anim.stop()
        self._hero_anim.setStartValue(self.hero.heroHeight)
        self._hero_anim.setEndValue(target_height)
        self._hero_anim.start()

        progress = 1.0 - (target_height / max(1, self.hero.expanded_height))
        if not hasattr(self.hero, "_content_fx"):
            self.hero._content_fx = QGraphicsOpacityEffect(self.hero.content_container)
            self.hero.content_container.setGraphicsEffect(self.hero._content_fx)
        self.hero._content_fx.setOpacity(max(0.0, 1.0 - progress * 1.25))

        mini_visible = target_height <= 40
        if mini_visible != self.compact_bar.isVisible():
            self.compact_bar.setVisible(mini_visible)
            if mini_visible:
                self._elide_compact_title()

    def _get_current_cards(self) -> list[ArtistAlbumCard]:
        cards = []
        key = self.categories[self.tab_widget.currentIndex()].lower().replace(" ", "_")
        layout = self.grid_layouts.get(key)
        if layout:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and (widget := item.widget()) and isinstance(widget, ArtistAlbumCard):
                    cards.append(widget)
        return cards

    def _on_download_all_clicked(self):
        self._is_downloading_all = True
        all_items_data = []
        include_mvs = self.hero.include_mv_checkbox.isChecked()
        for category in self.categories:
            key = category.lower().replace(" ", "_")
            grid_layout = self.grid_layouts.get(key)
            if grid_layout:
                for i in range(grid_layout.count()):
                    item = grid_layout.itemAt(i)
                    if item and (widget := item.widget()) and isinstance(widget, ArtistAlbumCard):
                        if not include_mvs and widget.result_data.get('type') == 'music-videos':
                            continue
                        all_items_data.append(widget.result_data)
        
        if not all_items_data:
            return

        if hasattr(self.hero, 'download_all_btn'):
            btn = self.hero.download_all_btn
            btn.setEnabled(False)
            btn.setText(f"Queuing 0/{len(all_items_data)}...")
        
        self.download_requested.emit(all_items_data)

    @pyqtSlot(int, int)
    def on_discography_batch_progress(self, done, total):
        btn = self.hero.download_all_btn if self._is_downloading_all else self.download_selected_button
        try:
            if hasattr(self, 'hero') and not sip.isdeleted(btn):
                btn.setText(f"Adding to queue... ({done}/{total})")
        except RuntimeError:
            pass

    @pyqtSlot(int)
    def on_discography_batch_finished(self, total):
        try:
            if self._is_downloading_all:
                btn = self.hero.download_all_btn
                if hasattr(self, 'hero') and not sip.isdeleted(btn):
                    btn.setText("Added to queue.")

                    def restore_hero_button():
                        if hasattr(self, 'hero') and not sip.isdeleted(btn):
                            btn.setText("Download Discography")
                            btn.setEnabled(True)
                    
                    QTimer.singleShot(2000, restore_hero_button)
                self._is_downloading_all = False
            else:
                btn = self.download_selected_button
                if hasattr(self, 'download_selected_button') and not sip.isdeleted(btn):
                    btn.setText("Added to queue.")

                    def restore_selection_button():
                        if hasattr(self, 'download_selected_button') and not sip.isdeleted(btn):
                            self._clear_selection()
                            if not sip.isdeleted(btn):
                                btn.setEnabled(True)

                    QTimer.singleShot(2000, restore_selection_button)
        except RuntimeError:
            logging.warning("Artist page button was deleted before timer callback.")

    def _add_bottom_controls(self):
        self.bottom_bar = QFrame()
        lay = QHBoxLayout(self.bottom_bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        self.selection_controls_widget = QWidget()
        selection_layout = QHBoxLayout(self.selection_controls_widget)
        selection_layout.setContentsMargins(0,0,0,0)
        selection_layout.setSpacing(8)
        
        self.download_selected_button = QPushButton("Download Selected")
        self.download_selected_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_selected_button.setStyleSheet("font-weight: bold; padding: 6px 12px; background-color: #B03400; border: none; border-radius: 4px;")
        self.download_selected_button.clicked.connect(self._on_download_selected_clicked)
        
        self.view_selection_button = QPushButton("View Selection")
        self.view_selection_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_selection_button.clicked.connect(self._show_selection_dropdown)
        
        selection_layout.addWidget(self.download_selected_button)
        selection_layout.addWidget(self.view_selection_button)
        self.selection_controls_widget.hide()

        self.selection_dropdown = SelectionDropdown(self)
        self.selection_dropdown.remove_single_item_requested.connect(self._remove_single_selection)
        self.selection_dropdown.clear_all_requested.connect(self._clear_selection)
        self.selection_dropdown.clear_selected_requested.connect(self._on_clear_selected_requested)

        self.bottom_select_all_btn = QPushButton("Select All")
        self.bottom_select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bottom_select_all_btn.setStyleSheet("padding: 6px 12px;")
        self.bottom_select_all_btn.clicked.connect(self._select_all_current)

        self.bottom_deselect_btn = QPushButton("Deselect All")
        self.bottom_deselect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bottom_deselect_btn.setStyleSheet("padding: 6px 12px;")
        self.bottom_deselect_btn.clicked.connect(self._deselect_current)

        lay.addStretch()
        lay.addWidget(self.selection_controls_widget)
        lay.addWidget(self.bottom_select_all_btn)
        lay.addWidget(self.bottom_deselect_btn)

        self.main_layout.addWidget(self.bottom_bar)

    def _select_all_current(self):
        for card in self._get_current_cards():
            card.setSelected(True)

    def _deselect_current(self):
        for card in self._get_current_cards():
            card.setSelected(False)

    def _on_download_selected_clicked(self):
        if self.download_selected_button.isEnabled():
            self._is_downloading_all = False
            selected_items = [v['data'] for v in self.selection_manager.values()]
            if selected_items:
                self.download_selected_button.setEnabled(False)
                self.download_requested.emit(selected_items)

    def _create_tab(self, title):
        category = title.lower().replace(" ", "_")
        tab = QWidget()
        self.tab_widget.addTab(tab, title)
        
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 5, 10, 5)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QScroller.grabGesture(scroll_area.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        self.scroll_areas[category] = scroll_area
        
        container = QWidget()
        self.grid_containers[category] = container
        
        grid_layout = QGridLayout(container)
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid_layout.setSpacing(4)
        self.grid_layouts[category] = grid_layout
        
        scroll_area.setWidget(container)
        tab_layout.addWidget(scroll_area)

    def populate_album_list(self, discography: list):
        main_window = self.window()
        if main_window and hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage("Discography loaded.", 5000)

        self.hide_loading_state()
        albums, eps, singles, compilations, videos = [], [], [], [], []
        for item in discography:
            attrs = item.get('attributes', {})
            if not attrs: continue
            item_type = item.get('type')
            if item_type == 'music-videos':
                videos.append(item)
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
        self._populate_tab_content('music_videos', sorted(videos, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))
        self._populate_tab_content('compilations', sorted(compilations, key=lambda x: x.get('attributes', {}).get('releaseDate', ''), reverse=True))
        
        self._connect_scroll_events()
        QTimer.singleShot(0, self._reflow_all_grids)

    def _clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def _populate_tab_content(self, category, items):
        key = category.lower().replace(" ", "_")
        grid_layout = self.grid_layouts.get(key)
        if grid_layout is None:
            return

        self._clear_layout(grid_layout)

        if not items:
            parent_tab = self.grid_containers[key].parentWidget().parentWidget()
            if parent_tab:
                idx = self.tab_widget.indexOf(parent_tab)
                if idx != -1: self.tab_widget.setTabVisible(idx, False)
            return
        
        parent_tab = self.grid_containers[key].parentWidget().parentWidget()
        if parent_tab:
            idx = self.tab_widget.indexOf(parent_tab)
            if idx != -1: self.tab_widget.setTabVisible(idx, True)

        cols = max(1, self.width() // 200)
        for i, item_data in enumerate(items):
            card = ArtistAlbumCard(item_data)
            card.download_requested.connect(self.on_card_download_requested)
            card.tracklist_requested.connect(self.tracklist_requested.emit)
            card.info_requested.connect(self.info_requested.emit)
            card.selection_changed.connect(self._handle_selection_changed)
            
            main_window = self.window()
            if hasattr(main_window, 'card_widgets'):
                url = card.result_data.get('appleMusicUrl')
                if url:
                    if url not in main_window.card_widgets:
                        main_window.card_widgets[url] = weakref.WeakSet()
                    main_window.card_widgets[url].add(card)
            
            grid_layout.addWidget(card, i // cols, i % cols)

    @pyqtSlot(object)
    def on_card_download_requested(self, card_obj):
        if hasattr(card_obj, 'result_data'):
            self.download_requested.emit([card_obj.result_data])

    def show_loading_state(self):
        self.tab_widget.hide()
        self.segmented_header.hide()
        y = self.hero.geometry().bottom() + 20
        x = (self.width() - self.spinner.width()) // 2
        self.spinner.move(x, y)
        self.spinner.show()
        self.spinner.start()

    def hide_loading_state(self):
        if hasattr(self, "spinner") and self.spinner.isVisible():
            self.spinner.stop()
            self.spinner.hide()
        self.tab_widget.show()
        self.segmented_header.show()

    def _reflow_all_grids(self):
        for grid in self.grid_layouts.values():
            self._reflow_grid_layout(grid)

    def _reflow_grid_layout(self, layout):
        if not layout or not layout.parentWidget():
            return
            
        cols = max(1, self.width() // 200)
        
        widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widgets.append(item.widget())

        # Temporarily remove widgets from layout without deleting them
        for w in widgets:
            layout.removeWidget(w)

        # Re-add widgets with the new column count
        for i, widget in enumerate(widgets):
            layout.addWidget(widget, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(50, self._reflow_all_grids)

    def _update_selection_controls(self):
        count = len(self.selection_manager)
        self.selection_controls_widget.setVisible(count > 0)
        self.download_selected_button.setText(f"Download Selected ({count})")

    def _show_selection_dropdown(self):
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.close()
            return
        self.selection_dropdown.update_items({k: v['data'] for k, v in self.selection_manager.items()})
        self.selection_dropdown.show_under(self.view_selection_button, margin=8)

    def _clear_selection(self):
        urls_to_clear = list(self.selection_manager.keys())
        for url in urls_to_clear:
            self._remove_single_selection(url, update_controls=False)
        self._update_selection_controls()

    @pyqtSlot(list)
    def _on_clear_selected_requested(self, urls_to_clear):
        for url in urls_to_clear:
            self._remove_single_selection(url, update_controls=False)
        self._update_selection_controls()
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.update_items({k: v['data'] for k, v in self.selection_manager.items()})

    def _remove_single_selection(self, item_url: str, update_controls=True):
        if item_url in self.selection_manager:
            card = self.selection_manager[item_url]['card']
            if card and not sip.isdeleted(card):
             
                card.setSelected(False)

    @pyqtSlot(object, bool)
    def _handle_selection_changed(self, card, is_selected):
        item_url = card.result_data.get('appleMusicUrl')
        if not item_url:
            return
        
        if is_selected:
            self.selection_manager[item_url] = {
                'card': card,
                'data': card.result_data
            }
        else:
            self.selection_manager.pop(item_url, None)
            
        self._update_selection_controls()
        if self.selection_dropdown.isVisible():
            self.selection_dropdown.update_items({k: v['data'] for k, v in self.selection_manager.items()})
import weakref
import logging
import webbrowser
import yaml
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QScrollArea,
    QLabel, QFrame, QTabWidget, QStackedWidget, QStatusBar,
    QGraphicsDropShadowEffect, QSizePolicy, QStackedLayout, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, QSize, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap, QIcon
from PyQt6.QtSvg import QSvgRenderer
from ..controls import SegmentedQualitySelector, AACQualitySelector, QueueToggleBar, AnnouncementBanner
from ..utils import create_view_icon, render_svg_icon, resource_path
from core.workers import wrapper_pool
import requests
from PyQt6.QtCore import pyqtSignal, QObject, QRunnable, QThreadPool

class BroadcastSignals(QObject):
    finished = pyqtSignal(dict)

class BroadcastFetchTask(QRunnable):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.signals = BroadcastSignals()
        
    def run(self):
        import time
        try:
            bypass_cache_url = f"{self.url}?t={int(time.time())}"
            resp = requests.get(bypass_cache_url, timeout=5)
            if resp.status_code == 200:
                self.signals.finished.emit(resp.json())
            else:
                self.signals.finished.emit({})
        except Exception:
            self.signals.finished.emit({})


class WrapperStatusSignals(QObject):
    finished = pyqtSignal(str, bool, str)


class WrapperStatusTask(QRunnable):
    def run(self):
        from core.bridge_client import request_for, run_request
        try:
            with open(config_path(), 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}
        except Exception as exc:
            self.signals.finished.emit('', False, str(exc))
            return
        request = None
        try:
            request = request_for('status', settings=config)
            run_request(request)
            self.signals.finished.emit(request['wrapper'], True, '')
        except Exception as exc:
            self.signals.finished.emit(request['wrapper'] if request else '', False, str(exc))

    def __init__(self):
        super().__init__()
        self.signals = WrapperStatusSignals()


WRAPPER_BADGE_COLORS = {'checking': '#9a9a9a', 'connected': '#3ecf6e', 'offline': '#fd576b'}
WRAPPER_BADGE_ICONS = {
    'checking': "<circle cx='12' cy='12' r='10'/><path d='M12 6v6l4 2'/>",
    'connected': "<circle cx='12' cy='12' r='10'/><path d='m8 12 3 3 5-6'/>",
    'offline': "<circle cx='12' cy='12' r='10'/><path d='M12 16v-4'/><path d='M12 8h.01'/>",
}
WRAPPER_CHECK_INTERVAL_MS = 30000


def wrapper_label(key):
    from backend.router.common import WRAPPERS
    return WRAPPERS.get(key, 'Wrapper').replace(' (Default)', '')
from ...search_widgets import SearchLineEdit
from ...search_cards import SettingsButton
from ...settings_page import SettingsPage
from ...artwork_downloader_page import ArtworkDownloaderPage
from ...lyrics_downloader_page import LyricsDownloaderPage
from ...view_select import SelectionDropdown
from ..player_bar import PlayerBar
from ...queue_panel import QueuePanel
from ...artist import ArtistDiscographyPage
from core.config import config_path

TAB_STYLESHEET = """
    QTabWidget::pane {
        border: none;
    }
    QTabBar::tab {
        background: transparent;
        color: #aaa;
        padding: 8px 20px;
        margin: 2px;
        font-weight: bold;
        border: none;
    }
    QTabBar::tab:hover {
        color: #fff;
    }
    QTabBar::tab:selected {
        background-color: #fd576b;
        color: white;
        border-radius: 15px;
    }
    QTabBar {
        alignment: left;
        border: none;
    }
"""

class UiSetupFeatures:
    def on_quality_info_badge_clicked(self):
        if getattr(self, '_wrapper_state', '') == 'offline':
            self.open_settings_page()
        self._refresh_wrapper_status()

    def _refresh_wrapper_status(self):
        if getattr(self, '_wrapper_check_running', False):
            return
        self._wrapper_check_running = True
        if getattr(self, '_wrapper_state', '') != 'connected':
            self._set_wrapper_badge('checking', getattr(self, '_wrapper_key', ''), '')
        task = WrapperStatusTask()
        task.signals.finished.connect(self._on_wrapper_status)
        self._wrapper_status_task = task
        wrapper_pool().start(task)

    def _on_wrapper_status(self, wrapper, connected, message):
        self._wrapper_check_running = False
        if getattr(self, '_is_shutting_down', False):
            return
        self._set_wrapper_badge('connected' if connected else 'offline', wrapper, message)

    def _set_wrapper_badge(self, state, wrapper, message):
        badge = getattr(self, 'quality_info_badge', None)
        if badge is None:
            return
        self._wrapper_state, self._wrapper_key = state, wrapper
        name = wrapper_label(wrapper)
        text, tooltip = {
            'checking': (f"Checking {name}...", "Checking the selected wrapper."),
            'connected': (f"{name} connected", f"{name} is running and ready. Click to check again."),
            'offline': (f"{name} not connected", (message or f"{name} is not reachable.") + "\nClick to open Settings."),
        }[state]
        color = WRAPPER_BADGE_COLORS[state]
        svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='{color}' "
               f"stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'>{WRAPPER_BADGE_ICONS[state]}</svg>")
        renderer = QSvgRenderer(svg.encode())
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        badge.setIcon(QIcon(pixmap))
        badge.setText(text)
        badge.setToolTip(tooltip)
        badge.setStyleSheet(f"""
            #QualityInfoBadge {{
                background-color: transparent;
                border: 1px solid {color};
                border-radius: 13px;
                padding: 4px 10px;
                color: {color};
                font-size: 8pt;
                font-weight: 600;
            }}
            #QualityInfoBadge:hover {{
                background-color: rgba(255, 255, 255, 0.06);
            }}
        """)
        badge.setMinimumWidth(badge.fontMetrics().horizontalAdvance(text) + 14 + 6 + 20)
        badge.updateGeometry()

    def _on_broadcast_fetched(self, data: dict):
        msg = data.get("message", "")
        url = data.get("url", "")
        msg_type = data.get("type", "info")
        if msg:
            self.announcement_banner.set_message(msg, url, msg_type)

    def setup_ui(self):
        self.base_widget = QWidget()
        self.setCentralWidget(self.base_widget)

        self.base_layout = QHBoxLayout(self.base_widget)
        self.base_layout.setContentsMargins(0, 0, 0, 0)
        self.base_layout.setSpacing(0)

        self._setup_sidebar()
        self.base_layout.addWidget(self.sidebar)

        main_content_wrapper = QWidget()
        main_content_layout = QHBoxLayout(main_content_wrapper)
        main_content_layout.setContentsMargins(0, 0, 0, 0)
        main_content_layout.setSpacing(0)

        self.main_content_container = QWidget()
        self.main_layout = QVBoxLayout(self.main_content_container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.page_stack = QStackedWidget()
        
        self.announcement_banner = AnnouncementBanner(self.main_content_container)
        self.announcement_banner.hide()
        self.main_layout.addWidget(self.announcement_banner)
        
        
        self.broadcast_url = "https://gist.github.com/rwnk-12/e20e0c4ace0ac4881af70fa96db62d60/raw"
        self.broadcast_task = BroadcastFetchTask(self.broadcast_url)
        self.broadcast_task.signals.finished.connect(self._on_broadcast_fetched)
        QThreadPool.globalInstance().start(self.broadcast_task)
        
        self.page_stack.currentChanged.connect(self._on_page_changed)
        self.main_layout.addWidget(self.page_stack, 1)

        self.player_bar = PlayerBar(self.main_content_container)
        self.main_layout.addWidget(self.player_bar)
        self.player_bar.hide()

        self.queue_toggle_bar = QueueToggleBar()
        self.queue_toggle_bar.clicked.connect(self.toggle_queue_panel)

        main_content_layout.addWidget(self.main_content_container, 1)
        main_content_layout.addWidget(self.queue_toggle_bar)
        
        self.base_layout.addWidget(main_content_wrapper, 1)

        self._setup_queue_panel()
        self.base_layout.addWidget(self.queue_panel)

        self.settings_page = SettingsPage(parent=self.page_stack)
        self.page_stack.addWidget(self.settings_page)

        self.artwork_page = ArtworkDownloaderPage(self.controller, self.page_stack)
        self.page_stack.addWidget(self.artwork_page)

        self.lyrics_page = LyricsDownloaderPage(self.controller, self.page_stack)
        self.page_stack.addWidget(self.lyrics_page)

        self._create_all_widgets()
        self._setup_results_view()
        
        self.setStatusBar(QStatusBar(self))

        self.popup_label = QLabel(self)
        self.popup_label.setObjectName("PopupLabel")
        self.popup_label.setStyleSheet("""
            #PopupLabel {
                background-color: #d32f2f;
                color: white;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
            }
        """)
        self.popup_label.hide()

        self.fetch_progress_popup = QLabel(self)
        self.fetch_progress_popup.setObjectName("FetchProgressPopup")
        self.fetch_progress_popup.setStyleSheet("""
            #FetchProgressPopup {
                background-color: #c45267;
                background-image: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 0.04),
                    stop:1 rgba(255, 255, 255, 0.03)
                );
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 4px 12px;
                border-radius: 16px;
                font-weight: bold;
                font-size: 8pt;
                font-family: "Inter Tight", sans-serif;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(27, 94, 32, 80))
        self.fetch_progress_popup.setGraphicsEffect(shadow)
        self.fetch_progress_popup.hide()

        self.main_content_container.installEventFilter(self)

    def _on_page_changed(self, index: int):
        if self._current_page_with_menu_signal:
            old_widget = self._current_page_with_menu_signal()
            if old_widget and hasattr(old_widget, 'menu_requested'):
                try:
                    old_widget.menu_requested.disconnect(self.toggle_sidebar)
                except TypeError:
                    pass
        
        new_widget = self.page_stack.widget(index)
        if new_widget and hasattr(new_widget, 'menu_requested'):
            new_widget.menu_requested.connect(self.toggle_sidebar)
            self._current_page_with_menu_signal = weakref.ref(new_widget)
        else:
            self._current_page_with_menu_signal = None

    def _highlight_sidebar(self, selected):
        for button in (self.home_button, self.settings_button_sidebar, self.artwork_button, self.lyrics_button):
            button.setStyleSheet(self.selected_button_style if button is selected else self.sidebar_button_style)

    def open_settings_page(self):
        self._highlight_sidebar(self.settings_button_sidebar)
        try:
            self.page_stack.setCurrentWidget(self.settings_page)
        except RuntimeError:
            self.settings_page = SettingsPage(parent=self.page_stack)
            self.page_stack.addWidget(self.settings_page)
            self.page_stack.setCurrentWidget(self.settings_page)

    def open_artwork_downloader_page(self):
        self._highlight_sidebar(self.artwork_button)
        try:
            self.page_stack.setCurrentWidget(self.artwork_page)
        except RuntimeError:
            self.artwork_page = ArtworkDownloaderPage(self.controller, self.page_stack)
            self.page_stack.addWidget(self.artwork_page)
            self.page_stack.setCurrentWidget(self.artwork_page)

    def open_lyrics_downloader_page(self):
        self._highlight_sidebar(self.lyrics_button)
        try:
            self.page_stack.setCurrentWidget(self.lyrics_page)
        except RuntimeError:
            self.lyrics_page = LyricsDownloaderPage(self.controller, self.page_stack)
            self.page_stack.addWidget(self.lyrics_page)
            self.page_stack.setCurrentWidget(self.lyrics_page)

    def _setup_sidebar(self):
        self.sidebar_width = 280
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setStyleSheet("#Sidebar { background-color: #252525; border-right: 1px solid #444; }")
        self.sidebar.setMaximumWidth(0)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 10)
        sidebar_layout.setSpacing(10)
        
        logo_label = QLabel(self.sidebar)
        logo_pixmap = QPixmap(resource_path("src/assets/apmyx.png"))
        if not logo_pixmap.isNull():
            scaled_pixmap = logo_pixmap.scaledToHeight(
                60, 
                Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setStyleSheet("background-color: transparent; margin-top: 3px; padding-bottom: 3px;")
            logo_label.setMaximumHeight(60)
            logo_label.setScaledContents(False)
        else:
            logo_label.setText("APMYX")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #f3576e; padding: 5px 0;")

        sidebar_layout.addWidget(logo_label)

        logo_separator = QFrame(self.sidebar)
        logo_separator.setFrameShape(QFrame.Shape.HLine)
        logo_separator.setFrameShadow(QFrame.Shadow.Sunken)
        logo_separator.setStyleSheet("QFrame { color: rgba(255, 255, 255, 0.15); margin: 3px 0 10px 0; }")
        sidebar_layout.addWidget(logo_separator)

        icon_color = "#f3576e"
        svg_home = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-house-icon lucide-house"><path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>"""
        svg_settings = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-cog-icon lucide-cog"><path d="M11 10.27 7 3.34"/><path d="m11 13.73-4 6.93"/><path d="M12 22v-2"/><path d="M12 2v2"/><path d="M14 12h8"/><path d="m17 20.66-1-1.73"/><path d="m17 3.34-1 1.73"/><path d="M2 12h2"/><path d="m20.66 17-1.73-1"/><path d="m20.66 7-1.73 1"/><path d="m3.34 17 1.73-1"/><path d="m3.34 7 1.73 1"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="12" r="8"/></svg>"""
        svg_artwork = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-image-down-icon lucide-image-down"><path d="M10.3 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10l-3.1-3.1a2 2 0 0 0-2.814.014L6 21"/><path d="m14 19 3 3v-5.5"/><path d="m17 22 3-3"/><circle cx="9" cy="9" r="2"/></svg>"""
        svg_lyrics = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-mic-vocal-icon lucide-mic-vocal"><path d="m11 7.601-5.994 8.19a1 1 0 0 0 .1 1.298l.817.818a1 1 0 0 0 1.314.087L15.09 12"/><path d="M16.5 21.174C15.5 20.5 14.372 20 13 20c-2.058 0-3.928 2.356-6 2-2.072-.356-2.775-3.369-1.5-4.5"/><circle cx="16" cy="7" r="5"/></svg>"""
        icon_size = 20

        self.sidebar_button_style = """
            QPushButton {
                border: none;
                background-color: transparent;
                color: #e0e0e0;
                text-align: left;
                padding: 8px;
                font-size: 10.8pt;
                font-weight: 500;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 10);
            }
        """

        self.selected_button_style = """
            QPushButton {
                border: none;
                background-color: rgba(60, 60, 60, 0.9);
                color: rgba(255, 255, 255, 1);
                text-align: left;
                padding: 8px;
                font-size: 10.9pt;
                font-weight: 500;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: rgba(70, 70, 70, 0.9);
            }
        """

        self.home_button = QPushButton("   Home")
        self.home_button.setIcon(render_svg_icon(svg_home, icon_color, icon_size))
        self.home_button.setIconSize(QSize(icon_size, icon_size))
        self.home_button.setStyleSheet(self.sidebar_button_style)
        self.home_button.clicked.connect(self._on_home_clicked)
        sidebar_layout.addWidget(self.home_button)

        self.settings_button_sidebar = QPushButton("   Settings")
        self.settings_button_sidebar.setIcon(render_svg_icon(svg_settings, icon_color, icon_size))
        self.settings_button_sidebar.setIconSize(QSize(icon_size, icon_size))
        self.settings_button_sidebar.clicked.connect(self.open_settings_page)
        self.settings_button_sidebar.setStyleSheet(self.sidebar_button_style)
        sidebar_layout.addWidget(self.settings_button_sidebar)

        self.artwork_button = QPushButton("   Artwork Downloader")
        self.artwork_button.setIcon(render_svg_icon(svg_artwork, icon_color, icon_size))
        self.artwork_button.setIconSize(QSize(icon_size, icon_size))
        self.artwork_button.clicked.connect(self.open_artwork_downloader_page)
        self.artwork_button.setStyleSheet(self.sidebar_button_style)
        sidebar_layout.addWidget(self.artwork_button)

        self.lyrics_button = QPushButton("   Lyrics Downloader")
        self.lyrics_button.setIcon(render_svg_icon(svg_lyrics, icon_color, icon_size))
        self.lyrics_button.setIconSize(QSize(icon_size, icon_size))
        self.lyrics_button.clicked.connect(self.open_lyrics_downloader_page)
        self.lyrics_button.setStyleSheet(self.sidebar_button_style)
        sidebar_layout.addWidget(self.lyrics_button)


        sidebar_layout.addSpacing(20)
        
        svg_github = """<svg width="98" height="96" xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" clip-rule="evenodd" d="M48.854 0C21.839 0 0 22 0 49.217c0 21.756 13.993 40.172 33.405 46.69 2.427.49 3.316-1.059 3.316-2.362 0-1.141-.08-5.052-.08-9.127-13.59 2.934-16.42-5.867-16.42-5.867-2.184-5.704-5.42-7.17-5.42-7.17-4.448-3.015.324-3.015.324-3.015 4.934.326 7.523 5.052 7.523 5.052 4.367 7.496 11.404 5.378 14.235 4.074.404-3.178 1.699-5.378 3.074-6.6-10.839-1.141-22.243-5.378-22.243-24.283 0-5.378 1.94-9.778 5.014-13.2-.485-1.222-2.184-6.275.486-13.038 0 0 4.125-1.304 13.426 5.052a46.97 46.97 0 0 1 12.214-1.63c4.125 0 8.33.571 12.213 1.63 9.302-6.356 13.427-5.052 13.427-5.052 2.67 6.763.97 11.816.485 13.038 3.155 3.422 5.015 7.822 5.015 13.2 0 18.905-11.404 23.06-22.324 24.283 1.78 1.548 3.316 4.481 3.316 9.126 0 6.6-.08 11.897-.08 13.526 0 1.304.89 2.853 3.316 2.364 19.412-6.52 33.405-24.935 33.405-46.691C97.707 22 75.788 0 48.854 0z" fill="currentColor"/></svg>"""
        
        github_icon_size = 22
        github_button = QPushButton("   Github")
        github_button.setIcon(render_svg_icon(svg_github, icon_color, github_icon_size))
        github_button.setIconSize(QSize(github_icon_size, github_icon_size))
        github_button.clicked.connect(lambda: webbrowser.open("https://github.com/rwnk-12/apmyx-gui"))
        github_button.setStyleSheet(self.sidebar_button_style)
        sidebar_layout.addWidget(github_button)

        svg_telegram = """<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-telegram" viewBox="0 0 16 16"><path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0M8.287 5.906q-1.168.486-4.666 2.01-.567.225-.595.442c-.03.243.275.339.69.47l.175.055c.408.133.958.288 1.243.294q.39.01.868-.32 3.269-2.206 3.374-2.23c.05-.012.12-.026.166.016s.042.12.037.141c-.03.129-1.227 1.241-1.846 1.817-.193.18-.33.307-.358.336a8 8 0 0 1-.188.186c-.38.366-.664.64.015 1.088.327.216.589.393.85.571.284.194.568.387.936.629q.14.092.27.187c.331.236.63.448.997.414.214-.02.435-.22.547-.82.265-1.417.786-4.486.906-5.751a1.4 1.4 0 0 0-.013-.315.34.34 0 0 0-.114-.217.53.53 0 0 0-.31-.093c-.3.005-.763.166-2.984 1.09"/></svg>"""
        telegram_button = QPushButton("   Telegram")
        telegram_button.setIcon(render_svg_icon(svg_telegram, icon_color, icon_size))
        telegram_button.setIconSize(QSize(icon_size, icon_size))
        telegram_button.clicked.connect(lambda: webbrowser.open("https://t.me/apmyx"))
        telegram_button.setStyleSheet(self.sidebar_button_style)
        sidebar_layout.addWidget(telegram_button)

        sidebar_layout.addStretch()

        version = getattr(self.controller, "VERSION", "")
        version_label = QLabel(f"v{version}" if isinstance(version, str) and version else "")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #777; font-size: 8pt; background-color: transparent; padding-bottom: 5px;")
        sidebar_layout.addWidget(version_label)

    def _on_home_clicked(self):
        try:
            self._highlight_sidebar(self.home_button)

            current_widget = self.page_stack.currentWidget()
            search_page = getattr(self, "search_results_page", None)

            if current_widget is search_page:
                return

            if isinstance(current_widget, ArtistDiscographyPage):
                self._navigate_back()
            elif search_page:
                self.page_stack.setCurrentWidget(search_page)
        except Exception as e:
            logging.warning(f"Error in _on_home_clicked: {e}")

    def _setup_queue_panel(self):
        self.queue_panel_width = 368
        self.queue_panel = QueuePanel(self)
        self.queue_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.queue_panel.setMinimumWidth(0)
        self.queue_panel.setMaximumWidth(0)

    def _create_all_widgets(self):
        self.settings_button = SettingsButton()
        self.search_input = SearchLineEdit()
        
        self.view_toggle_button = QPushButton()
        self.view_toggle_button.setFixedSize(32, 32)
        self.view_toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_toggle_button.setStyleSheet("border: 1px solid #555; border-radius: 4px; background-color: #3e3e3e;")
        self.view_toggle_button.clicked.connect(self._toggle_songs_view)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(TAB_STYLESHEET)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self._create_results_tab("Top Results")
        self._create_results_tab("Songs")
        self._create_results_tab("Albums")
        self._create_results_tab("Artists")
        self._create_results_tab("Music Videos")
        self._create_results_tab("Playlists")

        self._update_view_toggle_button()

        self.controls_widget = QWidget()
        controls_layout = QHBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 5, 0, 5)
        
        quality_label = QLabel("<b>Quality:</b>")
        controls_layout.addWidget(quality_label)

        self.quality_selector = SegmentedQualitySelector(("Atmos", "ALAC", "AAC"), accent="#B03400", parent=self.controls_widget)
        controls_layout.addWidget(self.quality_selector, 0, Qt.AlignmentFlag.AlignLeft)

        self.aac_quality_selector = AACQualitySelector(self.controls_widget)
        controls_layout.addWidget(self.aac_quality_selector, 0, Qt.AlignmentFlag.AlignLeft)
        self.aac_quality_selector.hide()

        self.quality_info_badge = QPushButton(self.controls_widget)
        self.quality_info_badge.setObjectName("QualityInfoBadge")
        self.quality_info_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quality_info_badge.setFlat(True)
        self.quality_info_badge.setIconSize(QSize(14, 14))
        self.quality_info_badge.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.quality_info_badge.setMinimumHeight(26)
        controls_layout.addWidget(self.quality_info_badge, 0, Qt.AlignmentFlag.AlignLeft)
        self.quality_info_badge.clicked.connect(self.on_quality_info_badge_clicked)
        self._wrapper_check_timer = QTimer(self)
        self._wrapper_check_timer.setInterval(WRAPPER_CHECK_INTERVAL_MS)
        self._wrapper_check_timer.timeout.connect(self._refresh_wrapper_status)
        self._wrapper_check_timer.start()
        self._refresh_wrapper_status()

        btns = self.quality_selector.buttons
        if len(btns) == 3:
            btns[0].setShortcut("Alt+1"); btns[0].setToolTip("Spatial Audio (Dolby Atmos) when available")
            btns[1].setShortcut("Alt+2"); btns[1].setToolTip("Lossless (ALAC), best fidelity for stereo")
            btns[2].setShortcut("Alt+3"); btns[2].setToolTip("High-Quality AAC, smaller files")

        self.selection_controls_widget = QWidget()
        selection_layout = QHBoxLayout(self.selection_controls_widget)
        selection_layout.setContentsMargins(0,0,0,0)
        selection_layout.setSpacing(10)
        self.download_selected_button = QPushButton("Download Selected (0)")
        self.live_queue_button = QPushButton("View Selection")
        self.selection_dropdown = SelectionDropdown(self)
        self.live_queue_button.clicked.connect(self.show_selection_dropdown)
        selection_layout.addWidget(self.download_selected_button)
        selection_layout.addWidget(self.live_queue_button)
        controls_layout.addWidget(self.selection_controls_widget)
        self.selection_controls_widget.hide()

        controls_layout.addStretch()
        controls_layout.addWidget(self.view_toggle_button)

        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFrameShadow(QFrame.Shadow.Sunken)

    def _update_view_toggle_button(self):
        if self.songs_view_mode == 'grid':
            self.view_toggle_button.setIcon(create_view_icon('list'))
            self.view_toggle_button.setToolTip("Switch to List View")
        else:
            self.view_toggle_button.setIcon(create_view_icon('grid'))
            self.view_toggle_button.setToolTip("Switch to Grid View")
        
        is_songs_tab = self.tab_widget.tabText(self.tab_widget.currentIndex()) == "Songs"
        self.view_toggle_button.setVisible(is_songs_tab)

    def _toggle_songs_view(self):
        if self.songs_view_mode == 'grid':
            self.songs_view_mode = 'list'
        else:
            self.songs_view_mode = 'grid'
        
        self._update_view_toggle_button()
        
        container = self.tab_containers.get('songs')
        if container:
            container.setUpdatesEnabled(False)

        if self.search_cache.get('songs'):
            self._populate_category_tab('songs', self.search_cache.get('songs', []))

        if container:
            container.setUpdatesEnabled(True)

    def _create_search_placeholder(self):
        placeholder = IntroPage()
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)
        layout.addStretch(1)

        logo = QLabel()
        pixmap = QPixmap(resource_path("src/assets/apmyx.png"))
        if pixmap.isNull():
            logo.setText("APMYX")
            logo.setStyleSheet("font-size: 28pt; font-weight: bold; color: #f3576e; background: transparent;")
        else:
            logo.setPixmap(pixmap.scaledToHeight(84, Qt.TransformationMode.SmoothTransformation))
            logo.setStyleSheet("background-color: #252526; border-radius: 16px; padding: 12px 22px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        note = QLabel("Search Apple Music, or paste a link to get started.")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color: #9a9a9a; font-size: 11pt; background: transparent;")

        disclaimer = QLabel("Not affiliated with Apple Inc.\nBuilt on publicly available open-source projects.")
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disclaimer.setStyleSheet("color: #6f6f6f; font-size: 9pt; background: transparent;")

        wrappers = [placeholder.reveal(widget) for widget in (logo, note, disclaimer)]
        for wrapper in wrappers:
            layout.addWidget(wrapper, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        placeholder.first_shown.connect(lambda: QTimer.singleShot(200, placeholder.play_intro))
        return placeholder

    def _setup_results_view(self):
        self.is_welcome_view = False

        self.search_results_page = QWidget()
        results_layout = QVBoxLayout(self.search_results_page)
        results_layout.setContentsMargins(10, 10, 10, 10)

        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)

        try:
            _ = self.settings_button.parent()
        except RuntimeError:
            from ...search_cards import SettingsButton
            self.settings_button = SettingsButton()
            self.settings_button.clicked.connect(self.toggle_sidebar)

        try:
            _ = self.search_input.parent()
        except RuntimeError:
            from ...search_widgets import SearchLineEdit
            self.search_input = SearchLineEdit()

        self.settings_button.setParent(header_container)
        self.search_input.setParent(header_container)
        self.search_input.setMaximumWidth(10000)
        header_layout.addWidget(self.settings_button)
        header_layout.addWidget(self.search_input)

        results_layout.addWidget(header_container)
        results_layout.addWidget(self.controls_widget)
        results_layout.addWidget(self.separator)
        results_layout.addWidget(self.tab_widget)

        self.page_stack.addWidget(self.search_results_page)
        self.page_stack.setCurrentWidget(self.search_results_page)

        self.settings_button.show()
        self.controls_widget.show()
        self.separator.show()
        self.tab_widget.show()
        self._update_view_toggle_button()

    def _create_results_tab(self, title):
        category_key = title.lower().replace(' ', '_')
        tab = QWidget()
        self.tab_widget.addTab(tab, title)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_areas[category_key] = scroll_area
        
        scroll_content = QWidget()
        self.tab_containers[category_key] = scroll_content
        scroll_area.setWidget(scroll_content)
        
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll_area)

        if category_key == 'top_results':
            stacked_layout = QStackedLayout(scroll_content)
            stacked_layout.setContentsMargins(0,0,0,0)
            
            self.search_placeholder_widget = self._create_search_placeholder()
            self.top_results_content_widget = QWidget()
            
            stacked_layout.addWidget(self.search_placeholder_widget)
            stacked_layout.addWidget(self.top_results_content_widget)
            
            stacked_layout.setCurrentWidget(self.search_placeholder_widget)
        
        if category_key not in ['top_results']:
            scroll_area.verticalScrollBar().valueChanged.connect(
                lambda value, cat=category_key: self.on_scroll(value, cat)
            )


class IntroPage(QWidget):
    first_shown = pyqtSignal()
    RISE = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown = False
        self._items = []
        self._animations = []

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            self.first_shown.emit()

    def reveal(self, widget):
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, self.RISE, 0, 0)
        box.setSpacing(0)
        box.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        self._items.append((wrapper, widget, effect))
        return wrapper

    def play_intro(self):
        for index, (wrapper, widget, effect) in enumerate(self._items):
            animation = QVariantAnimation(self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(700)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)

            def step(value, wrapper=wrapper, effect=effect):
                rise = round(self.RISE * (1.0 - value))
                wrapper.layout().setContentsMargins(0, rise, 0, self.RISE - rise)
                effect.setOpacity(value)

            animation.valueChanged.connect(step)
            animation.finished.connect(lambda widget=widget: widget.setGraphicsEffect(None))
            QTimer.singleShot(index * 160, animation.start)
            self._animations.append(animation)

from __future__ import annotations

import os
import yaml
import requests
import copy
from typing import Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRunnable, QThreadPool, QEvent, QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty, QRectF, QLocale
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton,
    QFormLayout, QLineEdit, QComboBox, QFileDialog, QSizePolicy, QDialog, QMessageBox, QApplication, QGraphicsDropShadowEffect,
    QGridLayout, QStackedWidget, QButtonGroup
)
from PyQt6.QtGui import QIntValidator, QPainter, QColor, QPen, QFont

from .search_cards import SettingsButton
from .settings_schema import (
    CATEGORIES as SCHEMA_CATEGORIES, CATEGORY_ORDER as SCHEMA_CATEGORY_ORDER,
    DEFAULTS as SCHEMA_DEFAULTS, HELP_TEXT as SCHEMA_HELP_TEXT,
    INTEGER_RANGES, OPTION_LABELS, LABELS,
    OPTIONS as SCHEMA_OPTIONS, PARTIAL_RESET_KEYS as SCHEMA_PARTIAL_RESET_KEYS,
    PLACEHOLDERS as SCHEMA_PLACEHOLDERS,
)
from core.bridge_client import request_for, run_request
from core.config import STOREFRONT_BACKUP, config_path as default_config_path, sync_storefront
from core import wrapper_lite
from backend.router.common import DEFAULTS as WRAPPER_DEFAULTS, WRAPPERS, UNSUPPORTED, migrate_wrapper
from backend.router.applemusicdecrypt.config import translate_settings as amd_settings, template as amd_template, VIDEO_TOKENS


ACCENT = "#fd576b"


class ToggleSwitch(QWidget):
    stateChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False
        self._thumb_pos = 2.0

        self.animation = QPropertyAnimation(self, b"thumb_pos", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.setDuration(150)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked == checked:
            return
        self._checked = checked
        self.animation.setStartValue(self.thumb_pos)
        self.animation.setEndValue(12.0 if self._checked else 2.0)
        self.animation.start()
        self.stateChanged.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        thumb_size = 18.0
        track_height = 12.0
        v_margin = (self.height() - track_height) / 2

        if self.isChecked():
            track_color = QColor("#5D0011")
            thumb_color = QColor("#FF3B30")
        else:
            track_color = QColor("#555555")
            thumb_color = QColor("#E0E0E0")

        track_rect = self.rect().adjusted(1, int(v_margin), -1, -int(v_margin))
        p.setBrush(track_color)
        p.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)

        p.setBrush(thumb_color)
        thumb_y = (self.height() - thumb_size) / 2
        thumb_rect = QRectF(self._thumb_pos, thumb_y, thumb_size, thumb_size)
        p.drawEllipse(thumb_rect)

    def mousePressEvent(self, event):
        self.setChecked(not self.isChecked())
        super().mousePressEvent(event)

    @pyqtProperty(float)
    def thumb_pos(self):
        return self._thumb_pos

    @thumb_pos.setter
    def thumb_pos(self, value):
        self._thumb_pos = value
        self.update()


class InfoButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none;")
        self.setToolTip("Click for more information")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isDown():
            painter.setBrush(QColor("#2a52be"))
        elif self.underMouse():
            painter.setBrush(QColor("#4169e1"))
        else:
            painter.setBrush(QColor("#3151a3"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())

        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        font = QApplication.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "i")

class InfoPopup(QDialog):
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoPopup")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet("#InfoPopup QLabel { background-color: transparent; }")


        bg_widget = QFrame(self)
        bg_widget.setObjectName("InfoPopupBg")
        bg_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bg_widget.setFixedWidth(550)
        bg_widget.setStyleSheet("""
            QFrame#InfoPopupBg {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2e2e2e, stop:1 #1f1f1f);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        bg_widget.setGraphicsEffect(shadow)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(bg_widget)

        content_layout = QVBoxLayout(bg_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(12)

        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_font = QFont()
        message_font.setPointSize(10)
        message_font.setBold(False)
        message_label.setFont(message_font)
        message_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.RichText)
        message_label.setOpenExternalLinks(True)
        content_layout.addWidget(message_label)

        for lab in (title_label, message_label):
            lab.setAutoFillBackground(False)
            lab.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lab.setStyleSheet("background-color: transparent; color: %s;" %
                              ("white" if lab is title_label else "#c0c0c0"))

        content_layout.addSpacing(15)

        ok_button = QPushButton("OK")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setFixedHeight(34)
        ok_button_font = QApplication.font()
        ok_button_font.setPointSize(10)
        ok_button_font.setBold(True)
        ok_button.setFont(ok_button_font)
        ok_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: #e55366;
            }}
        """)
        ok_button.clicked.connect(self.accept)
        content_layout.addWidget(ok_button)

        self.setFixedSize(self.sizeHint())

    def showEvent(self, e: QEvent):
        super().showEvent(e)
        parent = self.parent() or self
        screen = parent.window().screen().availableGeometry()
        self.adjustSize()
        g = self.frameGeometry()
        center = screen.center()
        g.moveCenter(center)

        x = max(screen.left() + 12, min(g.left(), screen.right() - g.width() - 12))
        y = max(screen.top() + 12, min(g.top(), screen.bottom() - g.height() - 12))
        self.move(x, y)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)

class StorefrontDetectorSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

class StorefrontDetector(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = StorefrontDetectorSignals()

    def run(self):
        try:
            r = requests.get("http://ip-api.com/json/", timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "success":
                cc = (data.get("countryCode") or "").lower()
                if cc:
                    self.signals.finished.emit(cc)
                else:
                    self.signals.error.emit("Geolocation API did not return a country code.")
            else:
                self.signals.error.emit(f"Geolocation API error: {data.get('message','Unknown API error')}")
        except Exception as e:
            self.signals.error.emit(str(e))



class SettingsPage(QWidget):
    settings_applied = pyqtSignal(dict)
    wrapper_state_changed = pyqtSignal()
    back_requested = pyqtSignal()
    menu_requested = pyqtSignal()

    DEFAULTS = SCHEMA_DEFAULTS

    PARTIAL_RESET_KEYS = SCHEMA_PARTIAL_RESET_KEYS

    CATEGORIES = SCHEMA_CATEGORIES


    CATEGORY_ORDER = SCHEMA_CATEGORY_ORDER

    OPTIONS = SCHEMA_OPTIONS

    PLACEHOLDERS = SCHEMA_PLACEHOLDERS

    HELP_TEXT = SCHEMA_HELP_TEXT

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self.config_path = str(config_path or default_config_path())
        self.thread_pool = QThreadPool.globalInstance()
        self.config: Dict[str, Any] = {}
        self.original: Dict[str, Any] = {}
        self.widgets: Dict[str, QWidget] = {}
        self.form_layouts: Dict[str, QFormLayout] = {}
        self._dirty = False

        self._load_config()
        self._build_ui()
        self._populate_panes()
        self._apply_styles()
        self._wire_actions()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._normalize_sizes)
        self._update_lite_controls()

    def _normalize_sizes(self):
        if self.layout():
            self.layout().activate()
        self.updateGeometry()
        for widget in self.widgets.values():
            if isinstance(widget, (QLineEdit, QComboBox)):
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _build_ui(self):
        self.setObjectName("SettingsPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.hero = QWidget()
        self.hero.setObjectName("SettingsHero")
        hero_lay = QHBoxLayout(self.hero)
        hero_lay.setContentsMargins(20, 20, 20, 20)
        hero_lay.setSpacing(15)

        self.menu_btn = SettingsButton(self.hero)
        self.menu_btn.setToolTip("Menu")
        hero_lay.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignLeft)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel("Settings")
        title_label.setObjectName("SettingsTitle")
        subtitle_label = QLabel("Configure downloads, quality, paths, and more.")
        subtitle_label.setObjectName("SettingsSubtitle")
        title_box.addWidget(title_label)
        title_box.addWidget(subtitle_label)
        hero_lay.addLayout(title_box, 1)
        root.addWidget(self.hero)

        main_content = QWidget()
        main_layout = QHBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.nav_pane = QFrame()
        self.nav_pane.setObjectName("NavPane")
        self.nav_pane.setFixedWidth(220)
        nav_layout = QVBoxLayout(self.nav_pane)
        nav_layout.setContentsMargins(10, 15, 10, 10)
        nav_layout.setSpacing(6)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)
        main_layout.addWidget(self.nav_pane)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("Separator")
        main_layout.addWidget(separator)

        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack, 1)
        root.addWidget(main_content, 1)

        self.bottom = QFrame()
        self.bottom.setObjectName("BottomBar")
        bl = QHBoxLayout(self.bottom)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addStretch()
        self.reset_btn = QPushButton("Reset to Defaults")
        self.cancel_btn = QPushButton("Cancel")
        self.apply_btn = QPushButton("Apply")
        self.save_btn = QPushButton("Save")
        for b in (self.reset_btn, self.cancel_btn, self.apply_btn, self.save_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bl.addWidget(b)

        self.apply_btn.hide()
        self.save_btn.setText("Save")
        self.save_btn.setToolTip("Save changes and close Settings")
        root.addWidget(self.bottom)

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QWidget#SettingsPage {{
                background-color: #262626;
                color: #e0e0d0;
            }}
            QFrame#NavPane {{
                background-color: #2a2a2a;
            }}
            QFrame#Separator {{
                background-color: #3a3a3a;
            }}
            QFrame {{ background: transparent; }}
            QWidget#SettingsHero {{
                background-color: #2a2a2a;
                border-bottom: 1px solid #3a3a3a;
            }}
            QLabel#SettingsTitle {{
                font-size: 24pt;
                font-weight: 800;
                color: white;
                background: transparent;
            }}
            QLabel#SettingsSubtitle {{
                font-size: 9.5pt;
                color: #b0b0b0;
                font-weight: normal;
                background: transparent;
            }}
            /* Navigation Buttons */
            QFrame#NavPane QPushButton {{
                text-align: left;
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
                background-color: transparent;
                color: #c0c0c0;
                font-weight: bold;
            }}
            QFrame#NavPane QPushButton:hover {{
                background-color: #383838;
                color: white;
            }}
            QFrame#NavPane QPushButton:checked {{
                background-color: #d60117;
                color: white;
            }}
            /* General Controls */
            QPushButton {{
                background-color: #3e3e3e;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 6px 14px;
                color: #eee;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #4a4a4a; }}
            QLineEdit, QComboBox {{
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 7px;
                font-weight: bold;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {ACCENT};
            }}
            QComboBox::drop-down {{ border: none; }}
            QLabel#TipLabel, QLabel#PreviewLabel {{
                color: #bbb;
                font-size: 8.5pt;
                font-weight: normal;
            }}
            QLabel#SettingLabel {{
                font-weight: bold;
                color: #e0e0e0;
            }}
            QLabel#SubheaderLabel {{
                font-size: 10pt;
                font-weight: bold;
                color: {ACCENT};
                padding-top: 10px;
                padding-bottom: 4px;
            }}
            QFrame#BottomBar {{
                background-color: #2a2a2a;
                border-top: 1px solid #3a3a3a;
            }}
            QScrollArea {{ border: none; }}
            QLineEdit[alert="true"] {{
                border: 1.5px solid #d60117;
            }}
            QLineEdit[alert="true"]:focus {{
                border: 1.5px solid #d60117;
            }}
        """)

        for btn in (self.save_btn, self.apply_btn):
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #d60117;
                    border:none;
                    color:white;
                    font-weight:bold;
                    padding: 6px 16px;
                }
                QPushButton:hover{
                    background-color: #e62237;
                }
            """)

    def _wire_actions(self):
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        self.reset_btn.clicked.connect(self._on_reset)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.apply_btn.clicked.connect(self._on_apply)
        self.save_btn.clicked.connect(self._on_save)
        self.nav_button_group.idClicked.connect(self.content_stack.setCurrentIndex)

    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            merged = copy.deepcopy(self.DEFAULTS)
            merged.update(migrate_wrapper(data))
            saved_tags = data.get('tag-options') or {}
            merged['tag-options'] = {
                key: saved_tags.get(key, value)
                for key, value in self.DEFAULTS['tag-options'].items()
            }
            if str(merged.get('lrc-format', '')).lower() == 'srt':
                merged['lrc-format'] = 'lrc'
            self.config = merged

        except FileNotFoundError:
            self.config = copy.deepcopy(self.DEFAULTS)
            self._write(self.config)

        except Exception:
            self.config = copy.deepcopy(self.DEFAULTS)

        self.config = sync_storefront(self.config)
        self.original = copy.deepcopy(self.config)

    def _iter_category_names_in_order(self) -> list[str]:
        base = list(self.CATEGORIES.keys())
        ordered = [c for c in self.CATEGORY_ORDER if c in self.CATEGORIES]
        tail = [c for c in base if c not in ordered]
        return [name for name in ordered + tail if name != "Wrapper"] + ["Wrapper"]

    def _populate_panes(self):
        nav_layout = self.nav_pane.layout()
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            widget.deleteLater()
        for button in self.nav_button_group.buttons():
            self.nav_button_group.removeButton(button)
            button.deleteLater()

        self.widgets.clear()
        self.form_layouts.clear()
        self.wrapper_rows = {}

        for cat_name in self._iter_category_names_in_order():
            nav_button = QPushButton(cat_name)
            nav_button.setCheckable(True)
            nav_button.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_layout.addWidget(nav_button)

            page_content = self._create_category_page(cat_name)

            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(page_content)

            page_index = self.content_stack.addWidget(scroll_area)
            self.nav_button_group.addButton(nav_button, page_index)

        if self.nav_button_group.buttons():
            self.nav_button_group.buttons()[0].setChecked(True)
            self.content_stack.setCurrentIndex(0)
        self._update_wrapper_fields()

    def _create_subheader(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SubheaderLabel")
        return label

    def _create_category_page(self, cat_name: str) -> QWidget:
        keys = self.CATEGORIES[cat_name]

        page_widget = QWidget()
        page_layout = QVBoxLayout(page_widget)
        page_layout.setContentsMargins(25, 20, 25, 20)
        page_layout.setSpacing(15)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if cat_name == "Metadata Tagging":
            presets_layout = QHBoxLayout()
            presets_layout.setSpacing(10)
            presets_layout.addWidget(QLabel("<b>Presets:</b>"))
            basic_btn = QPushButton("Basic")
            detailed_btn = QPushButton("Detailed")
            full_btn = QPushButton("Full")
            for btn in (basic_btn, detailed_btn, full_btn):
                presets_layout.addWidget(btn)
            presets_layout.addStretch()
            page_layout.addLayout(presets_layout)

            basic_btn.clicked.connect(lambda: self._apply_metadata_preset('basic'))
            detailed_btn.clicked.connect(lambda: self._apply_metadata_preset('detailed'))
            full_btn.clicked.connect(lambda: self._apply_metadata_preset('full'))

            grid_layout = QGridLayout()
            grid_layout.setSpacing(10)
            grid_layout.setColumnStretch(1, 1)
            grid_layout.setColumnStretch(3, 1)

            nested_bool_keys = [k for k in keys if '.' in k and isinstance(self._get_default_value(k), bool)]

            num_rows = (len(nested_bool_keys) + 1) // 2
            for i, key in enumerate(nested_bool_keys):
                checkbox, label_widget = self._make_field_widget(key)
                row = i % num_rows
                col = (i // num_rows) * 2
                grid_layout.addWidget(label_widget, row, col, Qt.AlignmentFlag.AlignRight)
                grid_layout.addWidget(checkbox, row, col + 1)
            page_layout.addLayout(grid_layout)
        else:
            form_layout = QFormLayout()
            form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form_layout.setHorizontalSpacing(15)
            form_layout.setVerticalSpacing(18)
            self.form_layouts[cat_name] = form_layout

            if cat_name == "General":
                form_layout.addRow(self._create_subheader("Credentials & Region"))
            elif cat_name == "Naming Formats":
                form_layout.addRow(self._create_subheader("Folder & File Naming"))

            non_bool_keys = [k for k in keys if not isinstance(self._get_default_value(k), bool)]
            bool_keys = [k for k in keys if isinstance(self._get_default_value(k), bool)]

            for key in non_bool_keys:
                if key == 'alac-save-folder' and cat_name == "General":
                    separator = QFrame()
                    separator.setFixedHeight(1)
                    separator.setStyleSheet("background-color: #444; margin-top: 10px; margin-bottom: 5px;")
                    form_layout.addRow(separator)
                    form_layout.addRow(self._create_subheader("Save Locations"))

                field_widget, label_widget = self._make_field_widget(key)
                form_layout.addRow(label_widget, field_widget)
                self.wrapper_rows[key] = (form_layout, field_widget)

            if bool_keys:
                for key in bool_keys:
                    toggle, label_widget = self._make_field_widget(key)
                    form_layout.addRow(label_widget, toggle)
                    self.wrapper_rows[key] = (form_layout, toggle)

            if cat_name == "Wrapper":
                self.wrapper_status = QLabel("Wrappers must be started and authenticated separately.")
                self.wrapper_status.setWordWrap(True)
                self.wrapper_check = QPushButton("Check connection")
                self.wrapper_check.clicked.connect(self._check_wrapper)
                form_layout.addRow(self.wrapper_check, self.wrapper_status)
                self.lite_controls = QWidget()
                lite_layout = QHBoxLayout(self.lite_controls)
                lite_layout.setContentsMargins(0, 0, 0, 0)
                self.lite_start = QPushButton("Start Wrapper Lite")
                self.lite_stop = QPushButton("Stop Wrapper Lite")
                self.lite_start.clicked.connect(lambda: self._run_lite_action('start'))
                self.lite_stop.clicked.connect(lambda: self._run_lite_action('stop'))
                lite_layout.addWidget(self.lite_start)
                lite_layout.addWidget(self.lite_stop)
                lite_layout.addStretch()
                form_layout.addRow(self.lite_controls)
                self.wrapper_reset = QPushButton("Reset Wrapper to Defaults")
                self.wrapper_reset.clicked.connect(self._on_reset_wrapper)
                form_layout.addRow(self.wrapper_reset)
            page_layout.addLayout(form_layout)

        return page_widget

    @staticmethod
    def _field_visible(key: str, wrapper: str) -> bool:
        visible = not key.startswith(('wrapper-v2-', 'applemusicdecrypt-'))
        if key.startswith('wrapper-v2-'):
            visible = wrapper == 'wrapper-v2'
        elif key.startswith('applemusicdecrypt-'):
            visible = wrapper == 'applemusicdecrypt'
        elif key.startswith('amd-') or key in ('save-cover-file', 'lyrics-mode'):
            visible = wrapper == 'applemusicdecrypt'
        if key in ('decrypt-m3u8-port', 'get-m3u8-port', 'get-m3u8-from-device'):
            visible = wrapper == 'legacy'
        return visible and key not in UNSUPPORTED[wrapper]

    def _update_wrapper_fields(self, *args):
        selector = self.widgets.get('wrapper')
        if selector is None:
            return
        wrapper = selector.currentData() or WRAPPER_DEFAULTS['wrapper']
        for key, (form, field) in getattr(self, 'wrapper_rows', {}).items():
            form.setRowVisible(field, self._field_visible(key, wrapper))
        for key, widget in self.widgets.items():
            widget.setEnabled(key not in UNSUPPORTED[wrapper])
            if key in UNSUPPORTED[wrapper]:
                widget.setToolTip('This setting is not supported by the selected backend.')
        self._sync_storefront_widgets()
        self._update_lyrics_fields()
        self._update_lite_controls()

    def _update_lite_controls(self, *args):
        controls = getattr(self, 'lite_controls', None)
        if controls is None or getattr(self, '_lite_worker', None) is not None:
            return
        url = self.widgets['applemusicdecrypt-url'].text() if 'applemusicdecrypt-url' in self.widgets else ''
        local = self.widgets['wrapper'].currentData() == 'applemusicdecrypt' and wrapper_lite.local_port(url) is not None
        controls.setVisible(local)
        if not local:
            return
        ready = wrapper_lite.installed()
        hint = '' if ready else (
            'Run setup-wrapper-lite-qemu.cmd once to install and sign in.' if os.name == 'nt'
            else 'Run ./setup-wrapper-lite-qemu.sh once to install and sign in.')
        for button in (self.lite_start, self.lite_stop):
            button.setEnabled(ready)
            button.setToolTip(hint)

    def _run_lite_action(self, action):
        port = wrapper_lite.local_port(self.widgets['applemusicdecrypt-url'].text())
        if port is None:
            return
        self.lite_start.setEnabled(False)
        self.lite_stop.setEnabled(False)
        self.wrapper_status.setText('Starting Wrapper Lite...' if action == 'start' else 'Stopping Wrapper Lite...')
        owner = self

        class Signals(QObject):
            finished = pyqtSignal(bool, str)

        class Task(QRunnable):
            def __init__(self):
                super().__init__()
                self.signals = Signals()

            def run(self):
                succeeded, message = (wrapper_lite.start if action == 'start' else wrapper_lite.stop)(port)
                self.signals.finished.emit(succeeded, message)

        task = Task()

        def finished(succeeded, message):
            owner._lite_worker = None
            owner.wrapper_status.setText(message)
            owner._update_lite_controls()
            owner.wrapper_state_changed.emit()

        task.signals.finished.connect(finished)
        self._lite_worker = task
        self.thread_pool.start(task)

    def _update_lyrics_fields(self, *args):
        mode = self.widgets.get('lyrics-mode')
        format_widget = self.widgets.get('lrc-format')
        if mode is not None and format_widget is not None:
            unsynced = self.widgets['wrapper'].currentData() == 'applemusicdecrypt' and mode.currentData() == 'unsynced'
            format_widget.setEnabled(not unsynced)
            format_widget.setToolTip('Unsynced lyrics use plain text (.txt).' if unsynced else 'LRC preserves line or word timing. TTML preserves the original structure.')

    def _sync_storefront_widgets(self, *args):
        general = self.widgets.get('storefront')
        selector = self.widgets.get('applemusicdecrypt-storefront')
        if general is None or selector is None:
            return
        config = sync_storefront(self._collect())
        if STOREFRONT_BACKUP in config:
            self.config[STOREFRONT_BACKUP] = config[STOREFRONT_BACKUP]
        else:
            self.config.pop(STOREFRONT_BACKUP, None)
        blocked = general.blockSignals(True)
        general.setText(str(config.get('storefront') or ''))
        general.blockSignals(blocked)
        active = STOREFRONT_BACKUP in config
        general.setEnabled(not active)
        row = self.wrapper_rows.get('storefront')
        if row is not None:
            row[1].setEnabled(not active)
        general.setToolTip('Using the storefront selected under Wrapper → Wrapper Lite.' if active else '')

    def _check_wrapper(self):
        self.wrapper_check.setEnabled(False)
        self.wrapper_status.setText('Checking connection...')
        if self.widgets['wrapper'].currentData() == 'applemusicdecrypt':
            self.widgets['applemusicdecrypt-storefront'].setPlaceholderText('Loading storefronts...')
        owner = self

        class Signals(QObject):
            finished = pyqtSignal(str, object)

        class Check(QRunnable):
            def __init__(self, settings):
                super().__init__()
                self.settings = settings
                self.signals = Signals()

            def run(self):
                result = None
                try:
                    result = run_request(request_for('status', settings=self.settings))
                    message = 'Connected to the selected wrapper.'
                except Exception as exc:
                    message = str(exc)
                self.signals.finished.emit(message, result)

        check = Check(self._collect())
        def finished(message, result):
            if getattr(owner, '_wrapper_check_worker', None) is not check:
                return
            if owner._wrapper_identity(owner._collect()) != owner._wrapper_identity(check.settings):
                owner._invalidate_applemusicdecrypt_regions()
                message = 'Connection settings changed. Check connection again.'
            elif result is not None and check.settings['wrapper'] == 'applemusicdecrypt':
                regions = result.get('regions', [])
                owner._set_applemusicdecrypt_regions(regions)
                message = f'Connected. {len(regions)} storefronts available.'
            elif result is None and check.settings['wrapper'] == 'applemusicdecrypt':
                owner._invalidate_applemusicdecrypt_regions()
            owner.wrapper_status.setText(message)
            owner.wrapper_check.setEnabled(True)
            owner._wrapper_check_worker = None
        check.signals.finished.connect(finished)
        self._wrapper_check_worker = check
        self.thread_pool.start(check)

    @staticmethod
    def _wrapper_identity(settings):
        return tuple(settings.get(key) for key in (
            'wrapper', 'applemusicdecrypt-url', 'applemusicdecrypt-api-key',
            'wrapper-v2-url', 'wrapper-v2-decrypt-host', 'wrapper-v2-decrypt-port',
            'decrypt-m3u8-port', 'get-m3u8-port',
        ))

    @staticmethod
    def _storefront_label(code):
        country = QLocale.territoryToString(QLocale.codeToTerritory(code))
        return f'{country} ({code.upper()})'

    def _set_applemusicdecrypt_regions(self, regions=None):
        widget = self.widgets.get('applemusicdecrypt-storefront')
        if widget is None:
            return
        selected = widget.currentData() or ''
        blocked = widget.blockSignals(True)
        try:
            widget.clear()
            widget.setPlaceholderText('Select storefront' if regions else 'Check connection to load storefronts')
            for code in sorted(set(regions or []), key=self._storefront_label):
                widget.addItem(self._storefront_label(code), code)
            if selected and widget.findData(selected) < 0:
                suffix = 'unavailable' if regions is not None else 'check connection'
                widget.addItem(f'{self._storefront_label(selected)} - {suffix}', selected)
                if regions is not None:
                    widget.model().item(widget.count() - 1).setEnabled(False)
            if not selected and regions:
                preferred = (self.widgets['storefront'].text() or '').strip().lower()
                selected = preferred if preferred in regions else regions[0] if len(regions) == 1 else ''
            widget.setCurrentIndex(widget.findData(selected) if selected else -1)
        finally:
            widget.blockSignals(blocked)
        if selected != (self.config.get('applemusicdecrypt-storefront') or ''):
            self._mark_dirty()
        self._sync_storefront_widgets()

    def _invalidate_applemusicdecrypt_regions(self):
        self._set_applemusicdecrypt_regions()

    def _get_config_value(self, key: str):
        if '.' in key:
            parent_key, child_key = key.split('.')
            return self.config.get(parent_key, {}).get(child_key)
        return self.config.get(key)

    def _get_default_value(self, key: str):
        if '.' in key:
            parent_key, child_key = key.split('.')
            return self.DEFAULTS.get(parent_key, {}).get(child_key)
        return self.DEFAULTS.get(key)

    def _make_field_widget(self, key: str):
        value = self._get_config_value(key)
        default_value = self._get_default_value(key)
        help_data = self.HELP_TEXT.get(key, {})
        tip_text = help_data.get('tip', '')
        info_title = help_data.get('info_title')
        info_body = help_data.get('info_body')

        if key in LABELS:
            label_text = LABELS[key]
        else:
            label_text = key.split('.')[-1].replace('-', ' ').replace('_', ' ').title()
            if 'Lrc' in label_text:
                label_text = label_text.replace('Lrc', 'LRC')

        label_container = QHBoxLayout()
        label_container.setContentsMargins(0,0,0,0)
        label_container.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label_container.setSpacing(5)
        label_widget = QLabel(label_text)
        label_widget.setObjectName("SettingLabel")
        label_container.addWidget(label_widget)

        if info_title and info_body:
            info_btn = InfoButton()
            info_btn.clicked.connect(lambda _, t=info_title, b=info_body: self._show_info_popup(t, b))
            label_container.addWidget(info_btn)

        label_wrapper = QWidget()
        label_wrapper.setLayout(label_container)

        if isinstance(default_value, bool):
            toggle = ToggleSwitch()
            toggle.setChecked(bool(value))
            if tip_text:
                toggle.setToolTip(tip_text)
                label_wrapper.setToolTip(tip_text)
            toggle.stateChanged.connect(self._mark_dirty)
            self.widgets[key] = toggle
            return toggle, label_wrapper

        field_container = QVBoxLayout()
        field_container.setSpacing(4)
        field_container.setContentsMargins(0,0,0,0)

        if key == "wrapper":
            widget = QComboBox()
            for wrapper_id, title in WRAPPERS.items():
                widget.addItem(title, wrapper_id)
            widget.setCurrentIndex(max(0, widget.findData(value or WRAPPER_DEFAULTS["wrapper"])))
            widget.currentIndexChanged.connect(self._mark_dirty)
            widget.currentIndexChanged.connect(self._update_wrapper_fields)
            field_container.addWidget(widget)
        elif key == 'applemusicdecrypt-storefront':
            widget = QComboBox()
            widget.setPlaceholderText('Check connection to load storefronts')
            selected = str(value or '').strip().lower()
            if selected:
                widget.addItem(f'{self._storefront_label(selected)} - check connection', selected)
                widget.setCurrentIndex(0)
            else:
                widget.setCurrentIndex(-1)
            widget.setToolTip('Optional for local wrappers, which need no selection. Selecting a storefront also applies it to searches and downloads while Wrapper Lite is active. The wrapper chooses an account automatically.')
            widget.currentIndexChanged.connect(self._mark_dirty)
            widget.currentIndexChanged.connect(self._sync_storefront_widgets)
            field_container.addWidget(widget)
        elif key in OPTION_LABELS:
            widget = QComboBox()
            for option, title in OPTION_LABELS[key].items():
                widget.addItem(title, option)
            widget.setCurrentIndex(max(0, widget.findData(value)))
            widget.currentIndexChanged.connect(self._mark_dirty)
            if key == 'lyrics-mode':
                widget.currentIndexChanged.connect(self._update_lyrics_fields)
            field_container.addWidget(widget)
        elif key in self.OPTIONS:
            widget = QComboBox()
            widget.addItems(self.OPTIONS[key])

            current_value_lower = str(value).lower()
            for i in range(widget.count()):
                if widget.itemText(i).lower() == current_value_lower:
                    widget.setCurrentIndex(i)
                    break

            widget.currentTextChanged.connect(self._mark_dirty)
            widget.setProperty("coerce_int", key in ("alac-max", "atmos-max", "mv-max", "amd-max-bit-depth"))
            field_container.addWidget(widget)
        else:
            widget = QLineEdit('' if value is None else str(value))
            if key == 'applemusicdecrypt-api-key':
                widget.setEchoMode(QLineEdit.EchoMode.Password)
                widget.setPlaceholderText('Leave blank for local wrappers')
                widget.setToolTip('Local wrappers do not need an API key. Enter one only if your hosted wrapper requires it.')
            widget.textChanged.connect(self._mark_dirty)
            if key in ('applemusicdecrypt-url', 'applemusicdecrypt-api-key'):
                widget.textChanged.connect(self._invalidate_applemusicdecrypt_regions)
            if key == 'applemusicdecrypt-url':
                widget.textChanged.connect(self._update_lite_controls)
            if isinstance(default_value, int):
                minimum, maximum = INTEGER_RANGES.get(key, (1, 2147483647))
                widget.setValidator(QIntValidator(minimum, maximum, widget))
            if key == 'playlist-song-file-format':
                widget.setPlaceholderText('Use Song File Format')

            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            row_layout.setContentsMargins(0,0,0,0)
            row_layout.addWidget(widget, 1)

            if key == 'storefront':
                widget.setMaxLength(2)
                detect = QPushButton("Detect")
                detect.setFixedWidth(70)
                detect.clicked.connect(lambda: self._show_storefront_detect_warning(widget, detect))
                row_layout.addWidget(detect)
            elif key.endswith('-save-folder'):
                browse = QPushButton("Browse…")
                browse.clicked.connect(lambda _, le=widget: self._browse_dir_into(le))
                row_layout.addWidget(browse)

            field_container.addLayout(row_layout)

        self.widgets[key] = widget

        if tip_text:
            tip_label = QLabel(tip_text)
            tip_label.setObjectName("TipLabel")
            tip_label.setWordWrap(True)
            field_container.addWidget(tip_label)

        if key in self.PLACEHOLDERS:
            chips_widget = QWidget()
            chips_layout = QGridLayout(chips_widget)
            chips_layout.setContentsMargins(0, 5, 0, 0)
            chips_layout.setSpacing(8)
            chips_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

            for index, token in enumerate(self.PLACEHOLDERS[key]):
                chip = QPushButton(token)
                chip.setStyleSheet("padding: 4px 9px; border-radius: 11px; font-size: 8.5pt; background-color: #3a3a3a; border: none; font-weight: bold;")
                chip.clicked.connect(lambda _, t=token: self._copy_to_clipboard(t))
                chips_layout.addWidget(chip, index // 4, index % 4)
            field_container.addWidget(chips_widget)

        container_widget = QWidget()
        container_widget.setLayout(field_container)
        return container_widget, label_wrapper

    def _apply_metadata_preset(self, preset: str):
        presets = {
            'basic': ['write-title', 'write-artist', 'write-album', 'write-album-artist', 'write-genre', 'write-date', 'write-disc-track'],
            'detailed': ['write-title', 'write-artist', 'write-album', 'write-album-artist', 'write-composer', 'write-genre', 'write-isrc', 'write-upc', 'write-date', 'write-copyright', 'write-publisher', 'write-disc-track'],
            'full': [k.split('.')[-1] for k in self.CATEGORIES['Metadata Tagging'] if k.rsplit('.', 1)[-1].startswith('write-')]
        }

        active_preset = [f"tag-options.{p}" for p in presets.get(preset, [])]

        for key, widget in self.widgets.items():
            if key.startswith('tag-options.') and isinstance(widget, ToggleSwitch):
                widget.setChecked(key in active_preset)

        self._mark_dirty()

    def _copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied '{text}' to clipboard", 2000)

    def statusBar(self):
        return self.parent().window().statusBar()

    def _show_info_popup(self, title: str, body: str):
        popup = InfoPopup(title, body, self)
        popup.exec()

    def _browse_dir_into(self, line: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", os.getcwd())
        if path: line.setText(path)

    def _show_storefront_detect_warning(self, line: QLineEdit, btn: QPushButton):
        title = "Storefront Detection Notice"
        body = ("This feature determines your storefront code (e.g., 'us') from your current IP address. "
                "If you are using a VPN, the detected code will reflect the VPN's location.<br><br>"
                "This setting <b>must</b> match your Apple account's registered country. "
                "If the auto-detected value is different, please correct it manually to prevent errors.")

        popup = InfoPopup(title, body, self)
        if popup.exec() == QDialog.DialogCode.Accepted:
            self._detect_storefront(line, btn)

    def _detect_storefront(self, line: QLineEdit, btn: QPushButton):
        btn.setEnabled(False); btn.setText("…")
        worker = StorefrontDetector()
        worker.signals.finished.connect(lambda sf: self._on_storefront_detected(sf, line, btn))
        worker.signals.error.connect(lambda err: self._on_storefront_error(err, btn))
        self.thread_pool.start(worker)

    def _on_storefront_detected(self, sf: str, line: QLineEdit, btn: QPushButton):
        line.setText(sf)
        btn.setEnabled(True); btn.setText("Detect")

    def _on_storefront_error(self, err: str, btn: QPushButton):
        QMessageBox.warning(self, "Detection failed", err)
        btn.setEnabled(True); btn.setText("Detect")

    def _mark_dirty(self, *args):
        self._dirty = True

    def _collect(self) -> Dict[str, Any]:
        out = copy.deepcopy(self.config)
        for key, w in self.widgets.items():
            value = None
            if isinstance(w, QComboBox):
                val = (w.currentData() or '') if key in ('wrapper', 'applemusicdecrypt-storefront') or key in OPTION_LABELS else w.currentText()
                if w.property("coerce_int"):
                    try: val = int(val)
                    except Exception: pass
                value = val
                if key in ('aac-type', 'mv-audio-type', 'lrc-format'):
                    value = value.lower()
            elif isinstance(w, QLineEdit):
                v = w.text()
                default_val = self._get_default_value(key)
                if isinstance(default_val, int):
                    try: value = int(v)
                    except Exception: value = 0
                else: value = v
            elif isinstance(w, ToggleSwitch):
                value = w.isChecked()

            if '.' in key:
                parent_key, child_key = key.split('.')
                if parent_key not in out:
                    out[parent_key] = {}
                out[parent_key][child_key] = value
            else:
                out[key] = value
        return out

    def _write(self, data: Dict[str, Any]):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not write config: {e}")
            return False

    def _confirm_discard(self) -> bool:
        r = QMessageBox.question(self, "Discard changes?", "You have unsaved changes. Are you sure you want to discard them?")
        return r == QMessageBox.StandardButton.Yes

    def _update_widgets_from_config(self):
        for key, w in self.widgets.items():
            value = self._get_config_value(key)

            if isinstance(w, QComboBox):
                if key in ('wrapper', 'applemusicdecrypt-storefront') or key in OPTION_LABELS:
                    if key == 'applemusicdecrypt-storefront' and value and w.findData(value) < 0:
                        w.addItem(f'{self._storefront_label(value)} - check connection', value)
                    w.setCurrentIndex(w.findData(value) if key == 'applemusicdecrypt-storefront' else max(0, w.findData(value)))
                    continue
                current_value_lower = str(value).lower()
                for i in range(w.count()):
                    if w.itemText(i).lower() == current_value_lower:
                        w.setCurrentIndex(i)
                        break
            elif isinstance(w, QLineEdit):
                w.setText('' if value is None else str(value))
            elif isinstance(w, ToggleSwitch):
                w.setChecked(bool(value))
        self._sync_storefront_widgets()

    def _on_reset_wrapper(self):
        reply = QMessageBox.question(
            self, "Reset Wrapper",
            "Reset the wrapper selection, endpoints, API key, and wrapper storefront to their defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        config = sync_storefront(self._collect())
        for key in WRAPPER_DEFAULTS:
            config[key] = copy.deepcopy(self.DEFAULTS[key])
        self.config = sync_storefront(config)
        blocked = [(widget, widget.blockSignals(True)) for widget in self.widgets.values()]
        try:
            self._update_widgets_from_config()
            self._invalidate_applemusicdecrypt_regions()
            self._update_wrapper_fields()
        finally:
            for widget, previous in blocked:
                widget.blockSignals(previous)
        self._wrapper_check_worker = None
        self.wrapper_check.setEnabled(True)
        self.wrapper_status.setText("Wrapper defaults restored. Save to keep changes, then check connection.")
        self._dirty = True

    def _on_reset(self):
        reply = QMessageBox.question(self, "Confirm Reset",
                                     "Reset naming, quality, artwork, lyrics, metadata, and download settings to their defaults?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.config = sync_storefront(self._collect())
            for key in self.PARTIAL_RESET_KEYS:
                if key in self.config and key in self.DEFAULTS:
                    self.config[key] = copy.deepcopy(self.DEFAULTS[key])


            self._update_widgets_from_config()
            self._dirty = True

            title = "Info"
            body = ("Download settings were reset to their defaults.\n\n"
                    "Your tokens, storefront, language, and save folders have been preserved.")
            self._show_info_popup(title, body)

    def _on_cancel(self):
        if self._dirty and not self._confirm_discard(): return
        self.config = copy.deepcopy(self.original)
        self._populate_panes()
        self._dirty = False
        self.back_requested.emit()

    def _on_apply(self):
        data = sync_storefront(self._collect())
        for key, widget in self.widgets.items():
            if (isinstance(widget, QLineEdit) and isinstance(self._get_default_value(key), int)
                    and self._field_visible(key, data['wrapper']) and not widget.hasAcceptableInput()):
                minimum, maximum = INTEGER_RANGES.get(key, (1, 2147483647))
                label = LABELS.get(key, key.replace('-', ' ').title())
                QMessageBox.warning(self, 'Invalid settings', f'{label} must be a whole number from {minimum} to {maximum}.')
                return False
        if data['wrapper'] == 'applemusicdecrypt':
            try:
                amd_settings({'operation': 'download', 'settings': data})
                amd_template(data.get('mv-file-format') or '{ArtistName} - {VideoName}', VIDEO_TOKENS)
            except Exception as exc:
                QMessageBox.warning(self, 'Invalid settings', str(exc))
                return False
        if not self._write(data):
            return False
        self.original = copy.deepcopy(data)
        self.config = copy.deepcopy(data)
        self._dirty = False
        self.settings_applied.emit(data)
        self.statusBar().showMessage("Settings applied.", 2000)
        return True

    def _on_save(self):
        if self._on_apply():
            self.back_requested.emit()


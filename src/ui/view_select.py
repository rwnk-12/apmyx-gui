from PyQt6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListView, QGraphicsDropShadowEffect, QStyledItemDelegate, QStyle, QApplication
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtSlot, QAbstractListModel, QModelIndex, QRect, QSize, QPoint
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QFont, QMouseEvent
)
from typing import List, Dict, Any, Optional


ACCENT_PINK = QColor("#fd576b")
ACCENT_ORANGE = QColor("#B03400")
WHITE_COLOR = QColor("#ffffff")
PRIMARY_TEXT_COLOR = QColor("#e0e0e0")
BACKGROUND_COLOR = QColor("#2c2c2c")
BORDER_COLOR = QColor("#444")
CHECKBOX_BORDER_COLOR = QColor("#888")

class SelectionModel(QAbstractListModel):
    """A model to hold the list of selected items, now with check state."""
    def __init__(self, items: Optional[List[Dict[str, Any]]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._items = items or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < self.rowCount()):
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.get("name", "Unknown Item")
        elif role == Qt.ItemDataRole.UserRole:
            return item.get("url", "")
        elif role == Qt.ItemDataRole.CheckStateRole:
            return item.get("checkState", Qt.CheckState.Unchecked)
        return None

    def setData(self, index: QModelIndex, value: Any, role: int) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        self._items[index.row()]["checkState"] = value
        self.dataChanged.emit(index, index, [role])
        return True

    def update_items(self, items: List[Dict[str, Any]]):
        """Resets the model with a new list of items."""
        self.beginResetModel()
        for item in items:
            item["checkState"] = Qt.CheckState.Unchecked
        self._items = items
        self.endResetModel()

class SelectionDelegate(QStyledItemDelegate):
 
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.font = QFont("Inter Tight", 10, QFont.Weight.Bold)

    def sizeHint(self, option, index) -> QSize:
        return QSize(100, 32)

    def _get_remove_button_rect(self, option_rect: QRect) -> QRect:
        size = 16
        margin = 8
        return QRect(
            option_rect.right() - size - margin,
            option_rect.y() + (option_rect.height() - size) // 2,
            size, size
        )

    def paint(self, painter: QPainter, option, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        name = index.data(Qt.ItemDataRole.DisplayRole)
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        is_hovered = option.state & QStyle.StateFlag.State_MouseOver

        if is_hovered:
            painter.fillRect(option.rect, QColor(255, 255, 255, 8))

        painter.setPen(BORDER_COLOR)
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

       
        check_size = 16
        check_rect = QRect(
            option.rect.left() + 12,
            option.rect.y() + (option.rect.height() - check_size) // 2,
            check_size, check_size
        )
        painter.setPen(QPen(CHECKBOX_BORDER_COLOR, 1.5))
        painter.setBrush(BACKGROUND_COLOR.lighter(120))
        painter.drawRoundedRect(check_rect, 4, 4)

        if check_state == Qt.CheckState.Checked:
            painter.setBrush(ACCENT_PINK)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(check_rect.adjusted(2, 2, -2, -2), 3, 3)

     
        remove_button_rect = self._get_remove_button_rect(option.rect)
        if is_hovered:
            painter.setPen(QPen(QColor("#aaa"), 2))
            painter.drawLine(remove_button_rect.topLeft(), remove_button_rect.bottomRight())
            painter.drawLine(remove_button_rect.topRight(), remove_button_rect.bottomLeft())

     
        text_rect = option.rect.adjusted(check_rect.right() + 10, 0, -remove_button_rect.width() - 12, 0)
        painter.setFont(self.font)
        painter.setPen(PRIMARY_TEXT_COLOR)
        elided_text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_text)

        painter.restore()

class SelectionView(QListView):
    
    selection_changed = pyqtSignal()
    remove_item_at_index = pyqtSignal(QModelIndex)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(SelectionDelegate(self))
        self.setMouseTracking(True)
        self._hover_index = QModelIndex()

    def mouseMoveEvent(self, e: QMouseEvent):
        super().mouseMoveEvent(e)
        index = self.indexAt(e.pos())
        if index != self._hover_index:
            if self._hover_index.isValid():
                self.viewport().update(self.visualRect(self._hover_index))
            self._hover_index = index
            if self._hover_index.isValid():
                self.viewport().update(self.visualRect(self._hover_index))

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if self._hover_index.isValid():
            self.viewport().update(self.visualRect(self._hover_index))
            self._hover_index = QModelIndex()

    def mousePressEvent(self, e: QMouseEvent):
        index = self.indexAt(e.pos())
        if index.isValid():
            delegate = self.itemDelegate()
            remove_rect = delegate._get_remove_button_rect(self.visualRect(index))
            if remove_rect.contains(e.pos()):
                self.remove_item_at_index.emit(index)
                return

            current_state = self.model().data(index, Qt.ItemDataRole.CheckStateRole)
            new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
            self.model().setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
            self.selection_changed.emit()
            return

        super().mousePressEvent(e)

class SelectionDropdown(QFrame):
   
    remove_single_item_requested = pyqtSignal(str)
    clear_all_requested = pyqtSignal()
    clear_selected_requested = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setObjectName("SelectionDropdownMain")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        
        self.container = QFrame(self)
        self.container.setObjectName("SelectionDropdownContainer")
        self.container.setStyleSheet(f"""
            #SelectionDropdownContainer {{
                background-color: {BACKGROUND_COLOR.name()};
                border: 1px solid {BORDER_COLOR.name()};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 2)
        self.container.setGraphicsEffect(shadow)
        main_layout.addWidget(self.container)

        content_layout = QVBoxLayout(self.container)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        title = QLabel("Selected Items")
        title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #e0e0e0; background: transparent;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        content_layout.addLayout(header_layout)

        self.model = SelectionModel()
        self.list_view = SelectionView(self)
        self.list_view.setModel(self.model)
        content_layout.addWidget(self.list_view, 1)

        hint_label = QLabel("Check items to remove them from the selection. Click anywhere to close this.")
        hint_label.setStyleSheet("font-size: 8pt; color: #888; background: transparent;")
        hint_label.setWordWrap(True)
        content_layout.addWidget(hint_label)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self.clear_selected_btn = QPushButton("Remove Checked")
        self.clear_all_btn = QPushButton("Clear All")
        footer_layout.addWidget(self.clear_selected_btn)
        footer_layout.addWidget(self.clear_all_btn)
        content_layout.addLayout(footer_layout)

        self._style_buttons()
        self._connect_signals()

        self.setFixedWidth(480)
        self._recalculate_height()

    def _style_buttons(self):
        self.clear_selected_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_selected_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: 1px solid {ACCENT_PINK.name()}; color: {ACCENT_PINK.name()}; padding: 6px 10px; border-radius: 8px; font-weight: bold; }}
            QPushButton:hover {{ background: rgba(253, 87, 107, 0.08); }}
            QPushButton:disabled {{ background: transparent; border-color: #555; color: #555; }}
        """)
        self.clear_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_all_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {ACCENT_ORANGE.name()}; color: white; border: none; padding: 6px 12px; border-radius: 8px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {ACCENT_ORANGE.darker(115).name()}; }}
        """)

    def _connect_signals(self):
        self.clear_all_btn.clicked.connect(self.clear_all_requested.emit)
        self.clear_selected_btn.clicked.connect(self._emit_clear_selected)
        self.list_view.selection_changed.connect(self._update_button_visibility)
        self.list_view.remove_item_at_index.connect(self._on_remove_item_requested)

    @pyqtSlot(QModelIndex)
    def _on_remove_item_requested(self, index: QModelIndex):
        if index.isValid():
            url = self.model.data(index, Qt.ItemDataRole.UserRole)
            if url:
                self.remove_single_item_requested.emit(url)

    def update_items(self, selection_dict: Dict[str, Any]):
        items = [{"url": k, "name": v.get("name", "")} for k, v in (selection_dict or {}).items()]
        self.model.update_items(items)
        self._recalculate_height()
        self._update_button_visibility()

    def _recalculate_height(self):
        row_count = self.model.rowCount()
        rows_to_show = min(6, max(1, row_count))  
        row_height = self.list_view.itemDelegate().sizeHint(QStyle.StateFlag.State_None, QModelIndex()).height()
        
        content_height = rows_to_show * row_height
        header_height = 32
        hint_height = 30
        footer_height = 40 if row_count > 0 else 0
        margins_and_spacing = 20 + 8 + 8 + 16 

        total_height = content_height + header_height + hint_height + footer_height + margins_and_spacing
        
        screen = self.screen() or QApplication.primaryScreen()
        max_height = int(screen.availableGeometry().height() * 0.6)
        
        
        self.resize(self.width(), min(int(total_height), max_height))

    def _update_button_visibility(self):
        has_items = self.model.rowCount() > 0
        has_selection = any(
            self.model.data(self.model.index(i, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            for i in range(self.model.rowCount())
        )
        self.clear_all_btn.setVisible(has_items)
        self.clear_selected_btn.setEnabled(has_selection)

    def _emit_clear_selected(self):
        urls_to_clear = [
            self.model.data(self.model.index(i, 0), Qt.ItemDataRole.UserRole)
            for i in range(self.model.rowCount())
            if self.model.data(self.model.index(i, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        ]
        if urls_to_clear:
            self.clear_selected_requested.emit(urls_to_clear)

    def show_under(self, anchor_widget: QWidget, margin: int = 10):
        """Shows the dropdown positioned optimally relative to the anchor."""
        self._recalculate_height() 
        screen = self.screen() or QApplication.primaryScreen()
        avail_geom = screen.availableGeometry()

        anchor_rect = anchor_widget.rect()
        anchor_global_top_left = anchor_widget.mapToGlobal(anchor_rect.topLeft())
        anchor_global_bottom_left = anchor_widget.mapToGlobal(anchor_rect.bottomLeft())

        dropdown_width = self.width()
        dropdown_height = self.height()

        x = anchor_global_top_left.x()
        if x + dropdown_width > avail_geom.right():
            x = anchor_widget.mapToGlobal(anchor_rect.topRight()).x() - dropdown_width
        x = max(avail_geom.left() + 10, x)

        space_above = anchor_global_top_left.y() - avail_geom.top()
        space_below = avail_geom.bottom() - anchor_global_bottom_left.y()

        y = anchor_global_top_left.y() - dropdown_height - margin
        if y < avail_geom.top() + 10 and space_below > space_above:
            y = anchor_global_bottom_left.y() + margin
        
        self.move(int(x), int(y))
        self.show()
        self.raise_()

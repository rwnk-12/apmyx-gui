from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QScrollArea,
    QFrame, QTabWidget, QGraphicsBlurEffect,
    QGraphicsDropShadowEffect, QBoxLayout, QGraphicsOpacityEffect,
    QListView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QApplication
)
from PyQt6.QtCore import (
    pyqtSignal, Qt, QTimer, QAbstractListModel, QModelIndex, QSize, QRect, QEvent, QPointF, QPoint,
    QRectF,
)
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFontMetrics, QPen, QFont, QPainterPath, QLinearGradient
import logging
from ..search_cards import resource_path, render_svg_tinted

class DiscographyGridDelegate(QStyledItemDelegate):
    def __init__(self, image_cache, parent=None):
        super().__init__(parent)
        self.image_cache = image_cache
        self._pm_cache = {}
        self.btn_size = 26
        
        self.tracklist_icon_pixmap = None
        try:
            tl_path = resource_path('src/assets/tracklist.svg')
            with open(tl_path, 'rb') as f:
                self.tracklist_icon_pixmap = render_svg_tinted(f.read(), QSize(20, 20), QColor("white"))
        except Exception as e:
            logging.warning(f"Grid delegate icon load failed: {e}")
        
        self.button_states = {
            'dl_normal': self._create_button_pixmap(QColor(0, 0, 0, 200), 'download'),
            'dl_hover': self._create_button_pixmap(QColor("#f5596d"), 'download'),
            'tl_normal': self._create_button_pixmap(QColor(0, 0, 0, 200), 'tracklist'),
            'tl_hover': self._create_button_pixmap(QColor("#f5596d"), 'tracklist'),
            'info_normal': self._create_button_pixmap(QColor(0, 0, 0, 200), 'info'),
            'info_hover': self._create_button_pixmap(QColor("#f5596d"), 'info'),
        }
        
        base_font = QApplication.font()
        base_pt = base_font.pointSize() or 9
        self.title_font = QFont(base_font)
        self.title_font.setPointSize(base_pt + 1)
        self.title_font.setWeight(QFont.Weight.DemiBold)
        self.details_font = QFont(base_font)
        self.details_font.setPointSize(base_pt)
        self.details_font.setWeight(QFont.Weight.Medium)
        self.overlay_font = QFont(base_font)
        self.overlay_font.setFamilies(["Inter Tight", "Inter", self.overlay_font.family()])
        self.overlay_font.setWeight(QFont.Weight.Bold)

        self.art_size = QSize(180, 180)
        self.tile_size = QSize(190, 250)
        self.radius = 12
        
    def _cached_scaled_rounded(self, url: str, size: QSize, radius: int, item_type: str = None) -> QPixmap | None:
        key = (url, size.width(), size.height(), radius, item_type)
        if key in self._pm_cache:
            return self._pm_cache[key]
        
        base = self.image_cache.get(url)
        if not base:
            return None
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), float(radius), float(radius))
        
        if item_type == 'music-videos':
            scaled = base.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            final_pixmap = QPixmap(size)
            final_pixmap.fill(QColor(40, 40, 40))
            
            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setClipPath(path)
            
            x = (size.width() - scaled.width()) // 2
            y = (size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
        else:
            scaled = base.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            
            final_pixmap = QPixmap(size)
            final_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled)
            painter.end()

        self._pm_cache[key] = final_pixmap
        return final_pixmap

    def _create_button_pixmap(self, bg_color: QColor, icon_type: str) -> QPixmap:
        pixmap = QPixmap(self.btn_size, self.btn_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawEllipse(pixmap.rect())

        if icon_type == 'download':
            self._paint_download_icon(painter, pixmap.rect())
        elif icon_type == 'tracklist' and self.tracklist_icon_pixmap:
            ix = (self.btn_size - self.tracklist_icon_pixmap.width()) // 2
            iy = (self.btn_size - self.tracklist_icon_pixmap.height()) // 2
            painter.drawPixmap(ix, iy, self.tracklist_icon_pixmap)
        elif icon_type == 'info':
            self._paint_info_icon(painter, pixmap.rect())
            
        painter.end()
        return pixmap

    def _get_button_rects(self, option: QStyleOptionViewItem) -> tuple[QRect, QRect]:
        art_rect = QRect(option.rect.x(), option.rect.y(), self.art_size.width(), self.art_size.height())
        margin = 8
        btn_size = self.btn_size
        spacing = 4
        tl_rect = QRect(art_rect.right() - btn_size - margin, art_rect.bottom() - btn_size - margin, btn_size, btn_size)
        dl_rect = QRect(tl_rect.x() - btn_size - spacing, tl_rect.y(), btn_size, btn_size)
        return dl_rect, tl_rect
        
    def _get_info_rect(self, option: QStyleOptionViewItem) -> QRect:
        art_rect = QRect(option.rect.x(), option.rect.y(), self.art_size.width(), self.art_size.height())
        margin, btn_size = 8, self.btn_size
        return QRect(art_rect.x() + margin, art_rect.bottom() - btn_size - margin, btn_size, btn_size)

    def _paint_info_icon(self, painter: QPainter, rect: QRect):
        w = rect.width()
        margin = int(w * 0.25)
        icon_size = w - 2 * margin
        icon_rect = QRectF(rect.x() + margin, rect.y() + margin, icon_size, icon_size)
        ring_thickness = max(2.0, icon_size * 0.12)

        ring_pen = QPen(Qt.GlobalColor.white, ring_thickness)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(icon_rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.white)
        cx = icon_rect.center().x()
        
        dot_y = icon_rect.top() + icon_size * 0.28
        dot_r = max(1.0, icon_size * 0.08)
        painter.drawEllipse(QPointF(cx, dot_y), dot_r, dot_r)
        
        stem_w = max(1.5, icon_size * 0.12)
        stem_h = icon_size * 0.42
        stem_top = icon_rect.top() + icon_size * 0.48
        stem_rect = QRectF(cx - stem_w/2, stem_top, stem_w, stem_h)
        painter.drawRoundedRect(stem_rect, stem_w/2, stem_w/2)

    def _paint_download_icon(self, painter: QPainter, rect: QRect):
        pen = QPen(Qt.GlobalColor.white)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        center_x = rect.center().x()
        center_y = rect.center().y()
        painter.drawLine(QPointF(center_x, center_y - 5), QPointF(center_x, center_y + 5))
        painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x - 4, center_y + 1))
        painter.drawLine(QPointF(center_x, center_y + 5), QPointF(center_x + 4, center_y + 1))
        painter.drawLine(QPointF(center_x - 6, center_y + 8), QPointF(center_x + 6, center_y + 8))

    def sizeHint(self, option, index):
        return self.tile_size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        data = index.data(Qt.ItemDataRole.DisplayRole) or {}
        attrs = data.get('attributes', {})
        item_type = data.get('type')
        r = option.rect
        
        parent_view = self.parent()
        is_hovered = False
        if isinstance(parent_view, DiscographyListView):
            is_hovered = (parent_view.hover_index() == index)

        card_m = max(6, min(12, int(option.rect.width() * 0.03)))
        card_rect = option.rect.adjusted(card_m, card_m, -card_m, -card_m)
        
        art_rect = QRect(card_rect.x(), card_rect.y(), self.art_size.width(), self.art_size.height())
        art_url = attrs.get('artwork', {}).get('url', '').replace('{w}', '256').replace('{h}', '256')
        
        pm = self._cached_scaled_rounded(art_url, self.art_size, self.radius, item_type)
        if pm:
            painter.drawPixmap(art_rect.topLeft(), pm)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(50, 50, 50))
            painter.drawRoundedRect(QRectF(art_rect), self.radius, self.radius)

        if item_type == 'music-videos':
            grad_h = 36
            grad_rect = QRect(art_rect.x(), art_rect.bottom() - grad_h, art_rect.width(), grad_h)
            grad = QLinearGradient(QPointF(grad_rect.topLeft()), QPointF(grad_rect.bottomLeft()))
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 110))
            painter.fillRect(grad_rect, grad)

        album_name = attrs.get('name', 'Unknown')
        artist_name = attrs.get('artistName', 'Unknown Artist')
        year = (attrs.get('releaseDate') or '')[:4]
        
        painter.setFont(self.title_font)
        fm_title = QFontMetrics(self.title_font)
        title_rect = QRect(card_rect.x(), art_rect.bottom() + 6, self.art_size.width(), fm_title.height())
        painter.setPen(QColor("#e0e0e0"))
        
        full_w = fm_title.horizontalAdvance(album_name)
        avail = title_rect.width()
        painter.save()
        painter.setClipRect(title_rect)
        
        if is_hovered and full_w > avail:
            base = getattr(parent_view, "_marquee_offset", 0)
            gap = 24
            period = full_w + gap
            xoff = -(base % period)
            painter.drawText(title_rect.translated(xoff, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), album_name)
            painter.drawText(title_rect.translated(xoff + period, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), album_name)
        else:
            painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             fm_title.elidedText(album_name, Qt.TextElideMode.ElideRight, title_rect.width()))
        painter.restore()

        painter.setFont(self.details_font)
        fm_artist = QFontMetrics(self.details_font)
        artist_rect = QRect(card_rect.x(), title_rect.bottom(), self.art_size.width(), fm_artist.height())
        painter.setPen(QColor("#aaa"))
        
        if item_type == 'music-videos':
            details_text = f"{artist_name} • {year}"
        else:
            details_text = artist_name
        
        painter.drawText(artist_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         fm_artist.elidedText(details_text, Qt.TextElideMode.ElideRight, artist_rect.width()))
    
        is_checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        if is_checked:
            ring = QPen(QColor("#fd576b"), 2)
            ring.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(art_rect.adjusted(1, 1, -1, -1), self.radius, self.radius)
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 60))
            painter.drawRoundedRect(QRectF(art_rect.adjusted(2, 2, -2, -2)), self.radius - 1, self.radius - 1)

            check_bg_rect = QRect(art_rect.right() - 22, art_rect.y() + 6, 16, 16)
            painter.setBrush(QColor("#fd576b"))
            painter.drawEllipse(check_bg_rect)
            pen = QPen(Qt.GlobalColor.white, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            cx, cy = check_bg_rect.center().x(), check_bg_rect.center().y()
            painter.drawLine(cx - 3, cy, cx - 1, cy + 3)
            painter.drawLine(cx - 1, cy + 3, cx + 4, cy - 2)

        if is_hovered:
            b = 4
            border_rect = card_rect.adjusted(-b, -b, b, b)
            border_rect = border_rect.intersected(option.rect.adjusted(1,1,-1,-1))
            pen = QPen(QColor("#666"))
            pen.setWidthF(1.5)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            hw = 0.5 * pen.widthF()
            inner = QRectF(border_rect).adjusted(hw, hw, -hw, -hw)
            painter.drawRoundedRect(inner, float(self.radius), float(self.radius))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 120))
            painter.drawRoundedRect(QRectF(art_rect), self.radius, self.radius)
            
            mouse_pos = parent_view.hover_pos() if hasattr(parent_view, "hover_pos") else QPoint(-1,-1)
            
            if item_type == 'music-videos':
                dl_rect, _ = self._get_button_rects(option)
                dl_pixmap = self.button_states['dl_hover'] if dl_rect.contains(mouse_pos) else self.button_states['dl_normal']
                painter.drawPixmap(dl_rect.topLeft(), dl_pixmap)
            else:
                track_count = attrs.get('trackCount') or 0
                track_text = f"{track_count} track" if track_count == 1 else f"{track_count} tracks"
                year = (attrs.get('releaseDate') or '')[:4]
                pad = 8
                painter.setPen(Qt.GlobalColor.white)
                painter.setFont(self.overlay_font)
                fm = QFontMetrics(self.overlay_font)
                x = art_rect.x() + pad
                y1 = art_rect.y() + pad + fm.ascent()
                painter.drawText(x, y1, track_text)
                y2 = y1 + fm.height()
                painter.drawText(x, y2, year)
                
                dl_rect, tl_rect = self._get_button_rects(option)
                info_rect = self._get_info_rect(option)

                info_pixmap = self.button_states['info_hover'] if info_rect.contains(mouse_pos) else self.button_states['info_normal']
                painter.drawPixmap(info_rect.topLeft(), info_pixmap)

                dl_pixmap = self.button_states['dl_hover'] if dl_rect.contains(mouse_pos) else self.button_states['dl_normal']
                painter.drawPixmap(dl_rect.topLeft(), dl_pixmap)

                tl_pixmap = self.button_states['tl_hover'] if tl_rect.contains(mouse_pos) else self.button_states['tl_normal']
                painter.drawPixmap(tl_rect.topLeft(), tl_pixmap)
    
        painter.restore()

    def editorEvent(self, event, model: QAbstractListModel, option, index):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            item_type = model.data(index, Qt.ItemDataRole.DisplayRole).get('type')
            dl_rect, tl_rect = self._get_button_rects(option)
            info_rect = self._get_info_rect(option)
            
            if item_type != 'music-videos':
                parent_view = self.parent()
                if hasattr(parent_view, "info_button_clicked") and info_rect.contains(event.pos()):
                    parent_view.info_button_clicked.emit(index)
                    return True
                if hasattr(parent_view, "download_button_clicked") and dl_rect.contains(event.pos()):
                    parent_view.download_button_clicked.emit(index)
                    return True
                if hasattr(parent_view, "tracklist_button_clicked") and tl_rect.contains(event.pos()):
                    parent_view.tracklist_button_clicked.emit(index)
                    return True
            else:
                parent_view = self.parent()
                if hasattr(parent_view, "download_button_clicked") and dl_rect.contains(event.pos()):
                    parent_view.download_button_clicked.emit(index)
                    return True

            current_state = model.data(index, Qt.ItemDataRole.CheckStateRole)
            new_state = Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked else Qt.CheckState.Checked
            model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
            return True
            
        return super().editorEvent(event, model, option, index)

class DiscographyListView(QListView):
    tracklist_button_clicked = pyqtSignal(QModelIndex)
    download_button_clicked = pyqtSignal(QModelIndex)
    info_button_clicked = pyqtSignal(QModelIndex)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hover_pos = QPoint(-1, -1)
        self._hover_index = QModelIndex()
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(30)
        self._marquee_timer.timeout.connect(self._tick_marquee)
        self._marquee_offset = 0
        
    def _tick_marquee(self):
        if not self._hover_index.isValid(): return
        self._marquee_offset += 1
        self.viewport().update(self.visualRect(self._hover_index))

    def updateGeometries(self):
        super().updateGeometries()
        sb = self.verticalScrollBar()
        if sb is not None:
            sb.setSingleStep(10)

    def mouseMoveEvent(self, event):
        prev_index = self._hover_index
        self._hover_pos = event.pos()
        idx = self.indexAt(self._hover_pos)

        if prev_index != idx:
            self._marquee_offset = 0
            if prev_index.isValid():
                self.viewport().update(self.visualRect(prev_index))
            self._hover_index = idx
            if self._hover_index.isValid():
                self.viewport().update(self.visualRect(self._hover_index))
                self._marquee_timer.start()
            else:
                self._marquee_timer.stop()
        
        cursor_set = False
        if self._hover_index.isValid():
            delegate = self.itemDelegateForIndex(self._hover_index)
            if isinstance(delegate, DiscographyGridDelegate):
                option = QStyleOptionViewItem()
                option.rect = self.visualRect(self._hover_index)
                dl_rect, tl_rect = delegate._get_button_rects(option)
                info_rect = delegate._get_info_rect(option)
                if dl_rect.contains(self._hover_pos) or tl_rect.contains(self._hover_pos) or info_rect.contains(self._hover_pos):
                    self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    cursor_set = True

        if not cursor_set:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)
        
    def leaveEvent(self, event):
        if self._hover_index.isValid():
            self.viewport().update(self.visualRect(self._hover_index))
        self._hover_pos = QPoint(-1, -1)
        self._hover_index = QModelIndex()
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._marquee_timer.stop()
        self._marquee_offset = 0
        super().leaveEvent(event)
        
    def hover_pos(self) -> QPoint:
        return self._hover_pos
    
    def hover_index(self) -> QModelIndex:
        return self._hover_index
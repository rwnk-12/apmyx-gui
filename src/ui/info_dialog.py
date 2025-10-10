from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog,
    QPushButton, QDialogButtonBox, QSizePolicy, QScrollArea,
    QFrame, QFormLayout, QApplication, QGraphicsOpacityEffect, QLayout, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import (pyqtSignal, pyqtSlot, QThreadPool, Qt, QTimer, QPropertyAnimation, QEasingCurve, 
                          QObject, QEvent, QParallelAnimationGroup, QSize, pyqtProperty, QSequentialAnimationGroup,
                          QPauseAnimation)
from PyQt6.QtGui import (QPixmap, QBitmap, QPainter, QColor, QLinearGradient, QFontMetrics, QPen, QFont,
                         QPainterPath)
import logging
import os
from .search_widgets import ImageFetcher, round_pixmap, ClickableLabel
from .search_cards import resource_path, render_svg_tinted

class ShimmerTag(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._sheen_pos = -0.5  
        self.setFixedHeight(22)

        self.animation_group = QSequentialAnimationGroup(self)
        
        shimmer_anim = QPropertyAnimation(self, b"sheenPosition", self)
        shimmer_anim.setStartValue(-0.5)
        shimmer_anim.setEndValue(1.5)
        shimmer_anim.setDuration(5000) 
        shimmer_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        pause_anim = QPauseAnimation(6000, self) 

        self.animation_group.addAnimation(shimmer_anim)
        self.animation_group.addAnimation(pause_anim)
        self.animation_group.setLoopCount(-1) 

      
        self.font = self.font()
        self.font.setPointSize(9)
        self.font.setWeight(QFont.Weight.Bold)
        
        fm = QFontMetrics(self.font)
        text_width = fm.horizontalAdvance(self._text)
        self.setFixedWidth(text_width + 12) 

    @pyqtProperty(float)
    def sheenPosition(self):
        return self._sheen_pos

    @sheenPosition.setter
    def sheenPosition(self, pos):
        self._sheen_pos = pos
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        
        painter.setFont(self.font)
        painter.setPen(QColor("#E2C25D"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)

       
        painter.save()
        
        path = QPainterPath()
        
        sheen_center_x = self._sheen_pos * self.width()
        sheen_width = self.width() * 0.3  
        tilt_offset = self.height() * 0.8 

        
        bottom_left_x = sheen_center_x - sheen_width / 2
        bottom_right_x = sheen_center_x + sheen_width / 2
        top_left_x = bottom_left_x - tilt_offset
        top_right_x = bottom_right_x - tilt_offset

        path.moveTo(bottom_left_x, self.height())
        path.lineTo(bottom_right_x, self.height())
        path.lineTo(top_right_x, 0)
        path.lineTo(top_left_x, 0)
        path.closeSubpath()

        
        painter.setClipPath(path)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        
        painter.restore()

    def showEvent(self, event):
        super().showEvent(event)
        if self.animation_group.state() != QPropertyAnimation.State.Running:
            self.animation_group.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.animation_group.state() == QPropertyAnimation.State.Running:
            self.animation_group.stop()

class _ElideOnResizeFilter(QObject):
    def __init__(self, label: QLabel, full_text: str, parent=None):
        super().__init__(parent or label)
        self.label = label
        self.full = full_text
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            fm = QFontMetrics(self.label.font())
            self.label.setText(fm.elidedText(self.full, Qt.TextElideMode.ElideRight, self.label.width()))
        return False

class _BottomFadeOverlay(QWidget):
    def __init__(self, parent, fade_height=28):
        super().__init__(parent)
        self._h = fade_height
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(31,31,31,  0))
        g.setColorAt(1.0, QColor(31,31,31,220))
        p.fillRect(self.rect(), g)
        p.end()

class CollapsibleSection(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        
        self._animation = None

        self.header = QPushButton(title)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setStyleSheet("""
            QPushButton{
                text-align:left; font-weight:600; padding:6px 8px; border:none;
                border-radius:8px; background:rgba(255,255,255,0.06); color:#e0e0e0;
            }
            QPushButton:checked{ background:rgba(255,255,255,0.10); }
        """)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 4, 8, 6)
        self.content_layout.setSpacing(4)

        self._clip = QWidget()
        self._clip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._clip.setStyleSheet("background: #1f1f1f;")
        clip_lay = QVBoxLayout(self._clip)
        clip_lay.setContentsMargins(0, 0, 0, 0)
        clip_lay.addWidget(self.content)
        
        self._clip.setMinimumHeight(0)
        self._clip.setMaximumHeight(0)
        self._clip.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(4)
        lay.addWidget(self.header)
        lay.addWidget(self._clip)

        self._clip_h = 0
        self._preview_height = 0

        self.header.toggled.connect(self._toggle)

    def set_preview_height(self, height: int):
        self._preview_height = max(0, height)

    def _getClipHeight(self) -> int:
        return self._clip_h

    def _setClipHeight(self, h: int):
        self._clip_h = max(0, int(h))
        self._clip.setMinimumHeight(self._clip_h)
        self._clip.setMaximumHeight(self._clip_h)

    clipHeight = pyqtProperty(int, fget=_getClipHeight, fset=_setClipHeight)

    def _toggle(self, checked: bool):
        if self._animation and self._animation.state() == QPropertyAnimation.State.Running:
            return

        rows = getattr(self, "_rows", [])
        if checked:
            for r in rows:
                r.setVisible(True)
            self.content.adjustSize()
            target_h = self.content.sizeHint().height()
            height_ease = QEasingCurve.Type.OutQuart
            base, per_100px, dur_max = 220, 80, 380
        else:
            for i, r in enumerate(rows):
                r.setVisible(i < 4)
            self.content.adjustSize()
            target_h = self._preview_height if self._preview_height > 0 else 0
            height_ease = QEasingCurve.Type.InOutCubic
            base, per_100px, dur_max = 180, 60, 320

        self._clip.setVisible(True)
        start_h = self._getClipHeight()
        delta = abs(target_h - start_h)
        dur = int(min(dur_max, max(base, base + (delta / 100.0) * per_100px)))

        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()

        self._animation = QPropertyAnimation(self, b"clipHeight", self)
        self._animation.setStartValue(start_h)
        self._animation.setEndValue(target_h)
        self._animation.setDuration(dur)
        self._animation.setEasingCurve(height_ease)
    

        def finish():
          
            if not checked and target_h == 0:
                self._clip.setVisible(False)
            self._animation = None

        self._animation.finished.connect(finish)
        self._animation.start()

def _make_tag(text: str, bg="#555", fg="#fff"):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        QLabel {{
            background:{bg}; color:{fg};
            border-radius:9px; padding:2px 6px;
            font: 9pt; font-weight:600;
            min-height:20px; max-height:20px;
        }}""")
    lbl.setFixedHeight(20)
    return lbl

def _make_gold_tag(text: str):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        QLabel {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #E2C25D, stop:0.5 #C7A148, stop:1 #9D7A24);
            color:#ffffff;
            border:1px solid #755915; border-radius:9px; padding:2px 6px;
            font: 9pt; font-weight:600;
            min-height:20px; max-height:20px;
        }}""")
    lbl.setFixedHeight(20)
    eff = QGraphicsDropShadowEffect(lbl)
    eff.setBlurRadius(6)
    eff.setColor(QColor(230, 190, 80, 120))
    eff.setOffset(0, 0)
    lbl.setGraphicsEffect(eff)
    return lbl

def _create_quality_widget(text: str, is_hires: bool = False) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    icon_label = QLabel()
    icon_label.setFixedSize(24, 24)
    
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    icon_path = resource_path('src/assets/lossless.svg')
    if os.path.exists(icon_path):
        try:
            with open(icon_path, 'rb') as f:
                svg_bytes = f.read()
            
            new_icon_width = 21
            new_icon_height = int(new_icon_width * (9.0 / 14.0))
            
            # Always tint with gray color
            icon_color = QColor("#ccc")
            rendered_pixmap = render_svg_tinted(svg_bytes, QSize(new_icon_width, new_icon_height), icon_color)
            
            painter = QPainter(pixmap)
            x_offset = (24 - new_icon_width) // 2
            y_offset = (24 - new_icon_height) // 2
            painter.drawPixmap(x_offset, y_offset, rendered_pixmap)
            painter.end()
        except Exception as e:
            logging.warning(f"Failed to load or render lossless.svg: {e}")
    else:
        logging.warning(f"lossless.svg not found at: {icon_path}")

    icon_label.setPixmap(pixmap)
    
    if is_hires:
        text_widget = ShimmerTag(text)
    else:
        text_widget = QLabel(text)
        text_widget.setStyleSheet("color: #cccccc; font-size: 9pt; font-weight: bold;")

    layout.addWidget(icon_label)
    layout.addWidget(text_widget)
    layout.addStretch()
    
    return container

class InfoDialog(QDialog):
    link_copied = pyqtSignal()

    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1f1f1f;
                color: #ffffff;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QFormLayout QLabel {
                color: #e0e0e0;
            }
            QLabel[objectName="titleLabel"] {
                color: #ffffff;
            }
            QLabel[objectName="artistLabel"] {
                color: #cccccc;
            }
            QDialogButtonBox {
                background-color: transparent;
            }
            QDialogButtonBox QPushButton {
                background-color: #555555;
                color: #ffffff;
                border: 1px solid #777777;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QDialogButtonBox QPushButton:hover {
                background-color: #666666;
            }
            QDialogButtonBox QPushButton:default {
                background-color: #fd576b;
                border-color: #fd576b;
            }
            QDialogButtonBox QPushButton:default:hover {
                background-color: #fe6b7d;
            }
            QFrame[frameShape="4"] {
                color: #555555;
                background-color: #555555;
            }
        """)

        self.item_data = item_data
        self.setWindowTitle("Details")
        
        
        if not item_data.get("tracks_data"):  
            self.setFixedSize(560, 480)
        else:  
            self.setMinimumSize(580, 500)
            self.resize(740, 560)

    
        self._last_font_sizes = {}

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self.header_widget = self._create_header()
        main_layout.addWidget(self.header_widget)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("QScrollArea { border: none; }")
        self._scroll_area.setMinimumHeight(300)
        self._scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._content_widget = QWidget()
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        self.form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.form_layout.setHorizontalSpacing(15)
        self.form_layout.setVerticalSpacing(4)
        self.form_layout.setContentsMargins(0, 0, 0, 0)

        self._populate_info(self.form_layout)
        content_layout.addWidget(self.form_widget)
        
        self._add_track_qualities_section(content_layout)

        self.notes_section = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_section)
        self.notes_layout.setContentsMargins(0, 8, 0, 0)
        self.notes_layout.setSpacing(4)
        self._add_editorial_notes(self.notes_layout)
        content_layout.addWidget(self.notes_section)

        content_layout.addStretch()

        self._scroll_area.setWidget(self._content_widget)
        main_layout.addWidget(self._scroll_area)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self._button_box.accepted.connect(self.accept)
        main_layout.addWidget(self._button_box)
        
        self._fade = _BottomFadeOverlay(self)
        self._fade.hide()
        self._scroll_area.verticalScrollBar().valueChanged.connect(self._update_fade)
        self._scroll_area.viewport().installEventFilter(self)

    def _update_fade(self):
        bar = self._scroll_area.verticalScrollBar()
        show = bar.maximum() > 0 and bar.value() < bar.maximum()
        self._fade.setVisible(show)
        if show:
            self._place_fade()

    def _place_fade(self):
        vp = self._scroll_area.viewport()
        r = vp.rect()
        top_left = vp.mapTo(self, r.topLeft())
        self._fade.setGeometry(top_left.x(), top_left.y() + r.height() - self._fade._h,
                               r.width(), self._fade._h)
        self._fade.raise_()

    def eventFilter(self, obj, ev):
        if obj is self._scroll_area.viewport() and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._update_fade)
        return super().eventFilter(obj, ev)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._update_fade)

    def _add_track_qualities_section(self, parent_layout):
        tracks = self.item_data.get('tracks_data', [])
        if not tracks:
            return

        
        self._section = CollapsibleSection(f"Track audio details ({len(tracks)})", self)
        
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0,0,0,0)
        header_layout.setSpacing(6)
        
        track_header = QLabel("Track")
        track_header.setStyleSheet("font-weight:700; color:#ccc;")
        header_layout.addWidget(track_header, 1)
        
        chips_header = QWidget()
        chips_header_layout = QHBoxLayout(chips_header)
        chips_header_layout.setContentsMargins(0,0,0,0)
        chips_header_layout.setSpacing(16)
        
        quality_header = QLabel("Quality")
        quality_header.setStyleSheet("font-weight:700; color:#bbb;")
        
        atmos_header = QLabel('Dolby Atmos<br><span style="font-size:9pt; color:#aaa;">Availability</span>')
        atmos_header.setTextFormat(Qt.TextFormat.RichText)
        atmos_header.setStyleSheet("font-weight:700; color:#bbb; line-height:.95;")
        
        chips_header_layout.addWidget(quality_header)
        chips_header_layout.addWidget(atmos_header)
        header_layout.addWidget(chips_header, 0, Qt.AlignmentFlag.AlignRight)
        
        self._section.content_layout.addWidget(header_row)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { border: none; border-top: 1px solid #3b3b3b; }")
        self._section.content_layout.addWidget(separator)

     
        self._section._rows = []
        for i, track in enumerate(tracks):
            attrs = track.get('attributes', {})

            row = QWidget()
            row.setMinimumHeight(26)  
            h = QHBoxLayout(row)
            h.setContentsMargins(0,0,0,0)
            h.setSpacing(6)

            num = attrs.get('trackNumber')
            name = attrs.get('name', 'Unknown')
            
            left = QLabel(f"{num:02d}. {name}" if isinstance(num, int) and num > 0 else name)
            left.setStyleSheet("font-weight:600;")
            left.setWordWrap(False)
            left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            h.addWidget(left, 1)

            _full = left.text()
            left.setToolTip(_full)
            flt = _ElideOnResizeFilter(left, _full, left)
            left.installEventFilter(flt)

            chips_box = QWidget()
            chips_lay = QHBoxLayout(chips_box)
            chips_lay.setContentsMargins(0,0,0,0)
            chips_lay.setSpacing(6)
            chips_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

            traits = set(attrs.get('audioTraits', []))
            sr = attrs.get('sampleRateHz')
            bd = attrs.get('bitDepth')

            if not bd:
                if 'hi-res-lossless' in traits:
                    bd = 24
                elif 'lossless' in traits:
                    bd = 16

            parts = []
            if isinstance(bd, int) and bd > 0:
                parts.append(f"{bd}B")
            if isinstance(sr, int) and sr > 0:
                khz = sr / 1000.0
                khz_text = f"{khz:.1f}" if abs(khz - int(khz)) > 1e-3 else f"{int(khz)}"
                parts.append(f"{khz_text}kHz")
            
            if parts:
                is_hires = (isinstance(bd, int) and bd >= 24 and isinstance(sr, int) and sr >= 96000)
                quality_text = " . ".join(parts)
                quality_widget = _create_quality_widget(quality_text, is_hires=is_hires)
                chips_lay.addWidget(quality_widget)

            t2 = _make_tag("Dolby Atmos", "#616161", "#fff") if 'atmos' in traits else _make_tag("Not Available", "#3d3d3d", "#fff")
            chips_lay.addWidget(t2)

            h.addWidget(chips_box, 0, Qt.AlignmentFlag.AlignRight)
            self._section.content_layout.addWidget(row)
            self._section._rows.append(row)

        
        def _measure_h(w): 
            return w.sizeHint().height() if w and w.isVisible() else 0
        
        rows = self._section._rows
        lay = self._section.content_layout
        spacing = lay.spacing()
        margins = lay.contentsMargins()
        
        preview_h = (_measure_h(header_row) + 
                    _measure_h(separator) + 
                    sum(_measure_h(rows[i]) for i in range(min(4, len(rows)))) +
                    spacing * (min(4, len(rows)) + 1) + 
                    margins.top() + margins.bottom())
        
        self._section.set_preview_height(preview_h)

      
        for i, row in enumerate(rows):
            row.setVisible(i < 4)
        
        
        self._section._setClipHeight(preview_h)
        self._section._clip.setVisible(True)

        self._section.content_layout.addStretch(1)
        parent_layout.addWidget(self._section)

    def _create_header(self):
        header_widget = QWidget()
        header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        self.art_label = QLabel()
        self.art_label.setFixedSize(70, 70)
        self.art_label.setStyleSheet("background-color: #333; border-radius: 6px;")
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setText("...")
        self.art_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(self.art_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(f"{self.item_data.get('name', 'Unknown')}")
        self.title_label.setWordWrap(True)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.title_label)

        self.artist_label = QLabel(f"{self.item_data.get('artist', 'Unknown Artist')}")
        self.artist_label.setWordWrap(True)
        self.artist_label.setObjectName("artistLabel")
        self.artist_label.setStyleSheet("color: #ccc; font-size: 10pt; font-style: italic;")
        self.artist_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.artist_label)

        self.copy_link_label = ClickableLabel("Copy Link", self.item_data.get('appleMusicUrl'), tooltip="Click to copy link")
        self.copy_link_label.clicked.connect(self._copy_link_to_clipboard)
        self.copy_link_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        info_layout.addWidget(self.copy_link_label)

        header_layout.addLayout(info_layout)

        self._fetch_artwork()
        return header_widget

    def _copy_link_to_clipboard(self, url):
        if url:
            clipboard = QApplication.instance().clipboard()
            clipboard.setText(url)
            self.link_copied.emit()

            sender = self.sender()
            if isinstance(sender, ClickableLabel):
                original_text = sender.text()
                sender.setText("Copied!")
            
                t = QTimer(sender)
                t.setSingleShot(True)
                def restore():
                    try:
                        sender.setText(original_text)
                    except RuntimeError:
                        pass 
                t.timeout.connect(restore)
                t.start(1500)

    def _fetch_artwork(self):
        artwork_url = self.item_data.get('artworkUrl', '').replace('600x600', '160x160')
        if artwork_url:
            worker = ImageFetcher(artwork_url).auto_cancel_on(self)
            worker.signals.image_loaded.connect(self._set_artwork)
            worker.signals.error.connect(self._on_artwork_error)
            QThreadPool.globalInstance().start(worker)

    @pyqtSlot(bytes)
    def _set_artwork(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            scaled = pixmap.scaled(self.art_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.art_label.setPixmap(round_pixmap(scaled, 6))

    @pyqtSlot(str)
    def _on_artwork_error(self, error_str: str):
        self.art_label.setText("No Art")

    def _add_info_row(self, layout, label_text, value):
        if value:
            label = QLabel(f"{label_text}:")
            label.setStyleSheet("font-size: 9pt; font-weight: bold; color: #e0e0e0;")
            
            content = QLabel(str(value))
            content.setWordWrap(True)
            content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            content.setStyleSheet("color: #f8586c; font-size: 9pt;")
            
            layout.addRow(label, content)

    def _add_info_row_widget(self, layout, label_text, widget):
        if widget:
            label = QLabel(f"{label_text}:")
            label.setStyleSheet("font-size: 9pt; font-weight: bold; color: #e0e0e0;")
            layout.addRow(label, widget)

    def _populate_info(self, layout):
        data = self.item_data
        item_type = data.get('type')

        self._add_info_row(layout, "Release Date", data.get('releaseDate'))
        self._add_info_row(layout, "Record Label", data.get('recordLabel'))
        self._add_info_row(layout, "Copyright", data.get('copyright'))

        if item_type == 'songs':
            self._add_info_row(layout, "Album", data.get('albumName'))
            self._add_info_row(layout, "Composer", data.get('composerName'))
            self._add_info_row(layout, "ISRC", data.get('isrc'))
            self._add_info_row(layout, "Contains Lyrics", "Yes" if data.get('hasLyrics') else "No")
            self._add_info_row(layout, "Time-Synced Lyrics", "Yes" if data.get('hasTimeSyncedLyrics') else "No")
        else:
            self._add_info_row(layout, "Total Tracks", data.get('trackCount'))
            self._add_info_row(layout, "UPC", data.get('upc'))
            self._add_info_row(layout, "Compilation", "Yes" if data.get('isCompilation') else "No")

        if data.get('genreNames'):
            self._add_info_row(layout, "Genres", ", ".join(data['genreNames']))

        tracks = data.get('tracks_data', [])
        total_tracks = data.get('trackCount') or len(tracks)
        
        if tracks:
            atmos_count = 0
            common_traits = set(tracks[0].get('attributes', {}).get('audioTraits', [])) if tracks else set()

            for track in tracks:
                track_traits = set(track.get('attributes', {}).get('audioTraits', []))
                if 'atmos' in track_traits:
                    atmos_count += 1
                common_traits.intersection_update(track_traits)
            
            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0,0,0,0)
            h_layout.setSpacing(6)
            
            has_widget = False

            quality_text = ""
            is_hires = False
            if 'hi-res-lossless' in common_traits:
                quality_text = "Hi-Res Lossless"
                is_hires = True
            elif 'lossless' in common_traits:
                quality_text = "Lossless"
            elif 'lossy-stereo' in common_traits:
                quality_text = "Standard"

            if quality_text:
                quality_widget = _create_quality_widget(quality_text, is_hires=is_hires)
                h_layout.addWidget(quality_widget)
                has_widget = True

            if 'atmos' in common_traits:
                atmos_tag = _make_tag("Dolby Atmos", "#616161", "#fff")
                h_layout.addWidget(atmos_tag)
                has_widget = True
            elif atmos_count > 0:
                atmos_tag = _make_tag(f"Dolby Atmos ({atmos_count}/{total_tracks})", "#616161", "#fff")
                h_layout.addWidget(atmos_tag)
                has_widget = True

            if has_widget:
                h_layout.addStretch()
                self._add_info_row_widget(layout, "Audio Quality", container)

        elif data.get('audioTraits'):
            sr = data.get('sampleRateHz')
            bd = data.get('bitDepth')
            traits = set(data.get('audioTraits', []))

            if not bd:
                if 'hi-res-lossless' in traits:
                    bd = 24
                elif 'lossless' in traits:
                    bd = 16

            parts = []
            if isinstance(bd, int) and bd > 0:
                parts.append(f"{bd}B")
            if isinstance(sr, int) and sr > 0:
                khz = sr / 1000.0
                khz_text = f"{khz:.1f}" if abs(khz - int(khz)) > 1e-3 else f"{int(khz)}"
                parts.append(f"{khz_text}kHz")
            
            if parts:
                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0,0,0,0)
                h_layout.setSpacing(6)
                
                is_hires = (isinstance(bd, int) and bd >= 24 and isinstance(sr, int) and sr >= 96000)
                quality_text = " . ".join(parts)
                
                quality_widget = _create_quality_widget(quality_text, is_hires=is_hires)
                h_layout.addWidget(quality_widget)
                
                if 'atmos' in traits:
                    atmos_tag = _make_tag("Dolby Atmos", "#616161", "#fff")
                    h_layout.addWidget(atmos_tag)
                
                h_layout.addStretch()
                
                self._add_info_row_widget(layout, "Audio Quality", container)
            else:
                formatted_traits = [t.replace('lossy-stereo', 'Standard').replace('lossless', 'Lossless').replace('hi-res-lossless', 'Hi-Res Lossless').replace('atmos', 'Dolby Atmos').replace('spatial', 'Spatial Audio').title() for t in data['audioTraits']]
                self._add_info_row(layout, "Audio Quality", ", ".join(formatted_traits))

        self._add_info_row(layout, "Apple Digital Master", "Yes" if data.get('isAppleDigitalMaster') else "No")

    def _add_editorial_notes(self, layout):
        notes = self.item_data.get('editorialNotes')
        if not notes:
            return

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        notes_header = QLabel("About")
        notes_header.setStyleSheet("font-size: 11pt; margin-top: 6px; margin-bottom: 2px; font-weight: bold;")
        layout.addWidget(notes_header)

        self._notes_label = QLabel(notes)
        self._notes_label.setObjectName("notesContent")
        self._notes_label.setWordWrap(True)
        self._notes_label.setTextFormat(Qt.TextFormat.RichText)
        self._notes_label.setStyleSheet("color: #bbb; font-size: 8pt; line-height: 1.3;")
        layout.addWidget(self._notes_label)
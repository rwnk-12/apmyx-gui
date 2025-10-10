from PyQt6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QScrollArea, QLabel, QHBoxLayout, QPushButton,
    QGraphicsDropShadowEffect, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QTimer, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap
from .download_job_widget import DownloadJobWidget

class ConfirmCancelDialog(QDialog):
    
    def __init__(self, title, message, confirm_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirmation")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

       
        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(320) 
        self.bg_widget.setStyleSheet("""
            QFrame {
                background-color: #2c2c2c;
                border-radius: 12px;
            }
        """)
        
        # Layouts
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.bg_widget)
        
        content_layout = QVBoxLayout(self.bg_widget)
        content_layout.setContentsMargins(25, 20, 25, 20)
        content_layout.setSpacing(8)

        # Title
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: white;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(title_label)

        # Message
        message_label = QLabel(message)
        message_font = QFont()
        message_font.setPointSize(10)
        message_label.setFont(message_font)
        message_label.setStyleSheet("color: #b0b0b0;")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        content_layout.addWidget(message_label)
        
        content_layout.addSpacing(15)

        # Buttons (now in a QVBoxLayout)
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        
        self.yes_button = QPushButton(confirm_text)
        self.no_button = QPushButton("No")

        for button in [self.yes_button, self.no_button]:
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(38) # Thinner buttons
            font = button.font()
            font.setPointSize(11)
            font.setBold(True)
            button.setFont(font)

        self.yes_button.setStyleSheet("""
            QPushButton {
                background-color: #d60117;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #e62237;
            }
        """)
        self.no_button.setStyleSheet("""
            QPushButton {
                background-color: #8b7b7e;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #9c8b8e;
            }
        """)

        self.yes_button.clicked.connect(self.accept)
        self.no_button.clicked.connect(self.reject)

        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        content_layout.addLayout(button_layout)
        
        self.setFixedSize(self.sizeHint())

class CancelAllButton(QPushButton):
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Cancel All Jobs")
        self.setStyleSheet("border: none;")
        self._is_hovering = False

    def enterEvent(self, event):
        self._is_hovering = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovering = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        if self.isDown():
            bg_color = QColor("#d32f2f")
        elif self._is_hovering:
            bg_color = QColor(255, 255, 255, 25)
        else:
            bg_color = QColor("transparent")
        
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())

        # 'X' Icon
        pen = QPen(QColor("#e0e0e0"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        margin = 9
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())

class QueuePanel(QFrame):
    job_cancellation_requested = pyqtSignal(int)
    cancel_all_requested = pyqtSignal()

    def __init__(self, main_window_ref, parent=None):
        super().__init__(parent)
        self.main_window = main_window_ref
        self.setObjectName("QueuePanel")
        self.setStyleSheet("""
            #QueuePanel { 
                background-color: #252525; 
                border-left: 1px solid #444; 
            }
            QLabel#placeholder {
                color: #888;
                font-size: 12pt;
            }
        """)


        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(-5)
        shadow.setYOffset(0)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.setGraphicsEffect(shadow)

        self.jobs = {}

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

      
        header_widget = QWidget()
        header_widget.setFixedHeight(55)
        header_widget.setStyleSheet("border-bottom: 1px solid #3a3a3a;")

        title_layout = QHBoxLayout(header_widget)
        title_layout.setContentsMargins(15, 0, 15, 0)
        title_layout.setSpacing(10)

        title_label = QLabel("Download Queue")
        title_label.setStyleSheet("""
            font-size: 13pt;
            font-weight: 500;
            color: #e0e0e0;
        """)
        title_layout.addWidget(title_label, 1)

        self.clear_finished_button = QPushButton("Clear Finished")
        self.clear_finished_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_finished_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #666;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 8pt;
                font-weight: bold;
                color: #bbb;
            }
            QPushButton:hover {
                background-color: #3e3e3e;
                border-color: #888;
                color: #fff;
            }
        """)
        self.clear_finished_button.setVisible(False)
        self.clear_finished_button.clicked.connect(self._on_clear_finished_clicked)
        title_layout.addWidget(self.clear_finished_button)

        self.cancel_all_button = CancelAllButton()
        self.cancel_all_button.clicked.connect(self._show_cancel_all_confirmation)
        self.cancel_all_button.setVisible(False)
        title_layout.addWidget(self.cancel_all_button)

        self.main_layout.addWidget(header_widget)

        self.pause_banner = QWidget()
        self.pause_banner.setObjectName("PauseBanner")
        self.pause_banner.setStyleSheet("""
            #PauseBanner {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4d4400, stop:1 #332d00);
                border-bottom: 1px solid #604d00;
            }
        """)
        pause_layout = QHBoxLayout(self.pause_banner)
        pause_layout.setContentsMargins(15, 8, 15, 8)
        pause_layout.setSpacing(10)

        self.pause_label = QLabel()
        self.pause_label.setWordWrap(True)
        self.pause_label.setStyleSheet("background-color: transparent; color: #ffc107; font-size: 8pt; font-weight: bold;")
        pause_layout.addWidget(self.pause_label, 1)

        self.resume_button = QPushButton(" Resume")
        self.resume_button.setCursor(Qt.CursorShape.PointingHandCursor)
        resume_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-circle-play-icon lucide-circle-play"><path d="M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997A1 1 0 0 1 9 14.996z"/><circle cx="12" cy="12" r="10"/></svg>'''
       
        from PyQt6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(resume_svg.encode('utf-8'))
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        renderer.render(p)
        p.end()
        self.resume_button.setIcon(QIcon(pixmap))
        self.resume_button.setStyleSheet("""
            QPushButton { background-color: #646366; color: white; border: none; border-radius: 4px; padding: 5px 10px; font-size: 8pt; font-weight: bold; }
            QPushButton:hover { background-color: #757477; }
        """)
        pause_layout.addWidget(self.resume_button)

        self.clear_paused_button = QPushButton("Clear Paused")
        self.clear_paused_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_paused_button.setStyleSheet("""
            QPushButton { background-color: #d60117; color: white; border: none; border-radius: 4px; padding: 5px 10px; font-size: 8pt; font-weight: bold; }
            QPushButton:hover { background-color: #e62237; }
        """)
        pause_layout.addWidget(self.clear_paused_button)
        self.pause_banner.hide()
        self.main_layout.addWidget(self.pause_banner)
       
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(4)

        self.placeholder_label = QLabel("Download queue is empty.")
        self.placeholder_label.setObjectName("placeholder")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(self.placeholder_label)

        scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(scroll_area)

    def get_job_widget(self, job_id: int):
        """Returns the job widget corresponding to the given job ID."""
        return self.jobs.get(job_id)

    def show_pause_banner(self, paused_count: int):
        
        message = f"Queue paused ({paused_count} items). Please ensure the wrapper is running correctly, then click Resume."
        self.pause_label.setText(message)
        self.pause_banner.show()
        self.cancel_all_button.hide() 

    def hide_pause_banner(self):
        """Hides the pause banner."""
        self.pause_banner.hide()
        self._update_button_states() 

    def set_shadow_enabled(self, enabled: bool):
        eff = self.graphicsEffect()
        if eff:
            eff.setEnabled(enabled)

    def _show_cancel_all_confirmation(self):
        dialog = ConfirmCancelDialog(
            "Cancel All Downloads?",
            "This will remove all ongoing and queued downloads from the list.",
            "Yes, Cancel All",
            self.main_window
        )
        
        # Center the dialog on the main window
        mw_rect = self.main_window.geometry()
        dialog.move(mw_rect.center() - dialog.rect().center())
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cancel_all_requested.emit()

    @pyqtSlot(int, str)
    def _show_single_job_cancel_confirmation(self, job_id, item_name):
        dialog = ConfirmCancelDialog(
            "Cancel Download?",
            f"Are you sure you want to cancel the download of \"{item_name}\"?",
            "Yes, Cancel",
            self.main_window
        )
        
        mw_rect = self.main_window.geometry()
        dialog.move(mw_rect.center() - dialog.rect().center())
        
        job_widget = self.jobs.get(job_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.job_cancellation_requested.emit(job_id)
        else:
            if job_widget and not job_widget.is_finished:
                job_widget.cancel_button.setText("Cancel")
                job_widget.cancel_button.setEnabled(True)

    def _on_clear_finished_clicked(self):
        # Iterate over a copy of items to allow modification during loop
        for job_id, widget in list(self.jobs.items()):
            if widget.is_finished:
                self.remove_job(job_id)

    def _update_button_states(self):
        has_finished_job = any(w.is_finished for w in self.jobs.values())
        has_unfinished_job = any(not w.is_finished for w in self.jobs.values())

        self.clear_finished_button.setVisible(has_finished_job)
        # Hide cancel all if the pause banner is visible
        self.cancel_all_button.setVisible(has_unfinished_job and self.pause_banner.isHidden())

    def add_job(self, job_id, item_data, quality_label):
        self.placeholder_label.hide()
        job_widget = DownloadJobWidget(job_id, item_data, self.main_window, quality_label, self)
        
        # Ensure progress bar is determinate from the start
        if job_widget.job_progress_bar.maximum() == 0:
            job_widget.job_progress_bar.setRange(0, 1000)

        job_widget.cancel_requested.connect(self.job_cancellation_requested.emit)
        job_widget.confirmation_requested.connect(self._show_single_job_cancel_confirmation)
        self.scroll_layout.addWidget(job_widget)
        self.jobs[job_id] = job_widget
        self._update_button_states()
        return job_widget

    @pyqtSlot(int, str, float, float)
    def update_job_progress(self, job_id, status_text, track_percent, overall_percent):
        if job_id in self.jobs:
            self.jobs[job_id].update_progress(status_text, track_percent, overall_percent)

    @pyqtSlot(int, str)
    def update_stream_label(self, jobid, label):
        print(f"DEBUG PYTHON: update_stream_label called - jobid={jobid}, label='{label}'")
        if jobid in self.jobs:
            print(f"DEBUG PYTHON: Found widget for job {jobid}, calling set_stream_label")
            self.jobs[jobid].set_stream_label(label)
        else:
            print(f"DEBUG PYTHON: No widget found for job {jobid}")

    @pyqtSlot(int, str)
    def handle_track_skipped(self, job_id, track_name):
        if job_id in self.jobs:
            self.jobs[job_id].add_skipped_track(track_name)

    @pyqtSlot(int, str)
    def handle_job_error_line(self, job_id, error_text):
        if job_id in self.jobs:
            self.jobs[job_id].append_error_log(error_text)

    @pyqtSlot(int)
    def cancel_job(self, job_id):
        """Handles UI update for a job cancelled from the queue before starting."""
        if job_id in self.jobs:
            job_widget = self.jobs[job_id]
            job_widget.set_finished("Cancelled from queue.", False, [])
            self._schedule_widget_removal(job_widget, job_id)
            self._update_button_states()

    def _schedule_widget_removal(self, widget, job_id):
        """Schedules a widget to be removed after a delay."""
        widget.setEnabled(False)
        QTimer.singleShot(5000, lambda: self.remove_job(job_id))

    def remove_job(self, job_id: int):
        """Removes the widget for the given job_id immediately."""
        widget = self.jobs.get(job_id)
        if widget:
            if job_id in self.jobs:
                del self.jobs[job_id]

            widget.hide()
            self.scroll_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
            
            if not self.jobs:
                self.placeholder_label.show()
            
            self._update_button_states()

    @pyqtSlot(int, bool, str, list)
    def finalize_job(self, job_id, success, message, skipped_tracks):
        if job_id in self.jobs:
            job_widget = self.jobs[job_id]
            job_widget.set_finished(message, success, skipped_tracks)

            if "cancel" in message.lower():
                self._schedule_widget_removal(job_widget, job_id)
        
        self._update_button_states()
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout, QPlainTextEdit, QProgressBar, QTextBrowser
)
from PyQt6.QtCore import Qt, QObject, QRegularExpression, QRunnable, QThreadPool, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPalette, QRegularExpressionValidator
from PyQt6.QtGui import QFont
import webbrowser

class StorefrontRequiredDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.storefront = ""
        self._detector = None
        self.setWindowTitle("Storefront Required")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(380)
        self.bg_widget.setStyleSheet("""
            QFrame {
                background-color: #2c2c2c;
                border-radius: 12px;
                border: 1px solid #444;
            }
            QLabel {
                background-color: transparent;
                border: none;
            }
            QLabel#Title { color: white; }
            QLabel#Body  { color: #b0b0b0; }
            QPushButton#Primary {
                background-color: #d60117;
                color: white;
                border: none;
                border-radius: 8px;
                height: 32px;
                font-size: 11pt;
                font-weight: bold;
                padding: 0 16px;
            }
            QPushButton#Primary:hover { background-color: #e62237; }
            QPushButton#Secondary {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 8px;
                height: 32px;
                font-size: 11pt;
                padding: 0 16px;
            }
            QPushButton#Secondary:hover { background-color: #666; }
            QPushButton#Primary:disabled, QPushButton#Secondary:disabled { background-color: #444; color: #888; }
            QLineEdit {
                background-color: #1f1f1f;
                color: white;
                border: 1px solid #555;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 12pt;
            }
            QLineEdit:focus { border: 1px solid #d60117; }
            QLabel#Hint  { color: #8a8a8a; }
            QLabel#Error { color: #fd576b; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.bg_widget)

        content = QVBoxLayout(self.bg_widget)
        content.setContentsMargins(24, 18, 24, 18)
        content.setSpacing(12)

        title = QLabel("Storefront Required")
        title.setObjectName("Title")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)

        body = QLabel(
            "Enter the two-letter country code of your Apple Music account, for example us, gb or jp. "
            "It must match the country your Apple account is registered in."
        )
        body.setObjectName("Body")
        bf = QFont(); bf.setPointSize(10)
        body.setFont(bf)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(body)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("us")
        palette = self.code_input.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#777777"))
        self.code_input.setPalette(palette)
        self.code_input.setMaxLength(2)
        self.code_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_input.setValidator(QRegularExpressionValidator(QRegularExpression("[A-Za-z]{0,2}"), self.code_input))
        self.code_input.textEdited.connect(self._on_code_edited)
        self.code_input.returnPressed.connect(self._save)
        self.detect_button = QPushButton("Detect")
        self.detect_button.setObjectName("Secondary")
        self.detect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detect_button.clicked.connect(self._detect)
        input_row.addWidget(self.code_input, 1)
        input_row.addWidget(self.detect_button)
        content.addLayout(input_row)

        self.hint = QLabel("Detect uses your IP address. With a VPN it shows the VPN's country.")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(self.hint)

        content.addSpacing(6)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("Secondary")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)

        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(self.save_button)
        button_layout.addStretch()

        content.addLayout(button_layout)

        self.setFixedSize(self.sizeHint())
        self.code_input.setFocus()

    def _on_code_edited(self, text):
        lowered = text.lower()
        if lowered != text:
            position = self.code_input.cursorPosition()
            self.code_input.setText(lowered)
            self.code_input.setCursorPosition(position)
        self.save_button.setEnabled(len(lowered) == 2)

    def _show_hint(self, text, error=False):
        self.hint.setObjectName("Error" if error else "Hint")
        self.hint.setText(text)
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def _detect(self):
        from ui.settings_page import StorefrontDetector
        self.detect_button.setEnabled(False)
        self.detect_button.setText("...")
        detector = StorefrontDetector()
        detector.signals.finished.connect(self._on_detected)
        detector.signals.error.connect(self._on_detect_failed)
        self._detector = detector
        QThreadPool.globalInstance().start(detector)

    def _on_detected(self, code):
        self.detect_button.setEnabled(True)
        self.detect_button.setText("Detect")
        self.code_input.setText(code.lower())
        self._on_code_edited(self.code_input.text())
        self._show_hint(f"Detected {code.upper()} from your IP address. Change it if your Apple account is registered elsewhere.")

    def _on_detect_failed(self, message):
        logging.error("Storefront detection failed: %s", message)
        self.detect_button.setEnabled(True)
        self.detect_button.setText("Detect")
        self._show_hint("Could not detect your country. Type the code yourself.", error=True)

    def _save(self):
        code = self.code_input.text().strip().lower()
        if len(code) != 2 or not code.isalpha():
            self._show_hint("Enter a two-letter country code, for example us.", error=True)
            return
        self.storefront = code
        self.accept()

class RestartDialog(QDialog):
  
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restart Required")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)


        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(360)
        self.bg_widget.setStyleSheet("""
            QFrame {
                background-color: #2c2c2c;
                border-radius: 12px;
                border: 1px solid #444;
            }
            QLabel {
                background-color: transparent;
                border: none;
            }
            QLabel#Title { color: white; }
            QLabel#Body  { color: #b0b0b0; }
            QPushButton#Primary {
                background-color: #d60117;
                color: white;
                border: none;
                border-radius: 8px;
                height: 32px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton#Primary:hover { background-color: #e62237; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.bg_widget)

        content = QVBoxLayout(self.bg_widget)
        content.setContentsMargins(24, 18, 24, 18)
        content.setSpacing(12)

        title = QLabel("Restart Required")
        title.setObjectName("Title")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)

        body = QLabel(
            "Settings have been changed that require an application restart to take effect."
        )
        body.setObjectName("Body")
        bf = QFont(); bf.setPointSize(10)
        body.setFont(bf)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(body)

        content.addSpacing(15)

        
        ok_button = QPushButton("OK")
        ok_button.setObjectName("Primary")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.clicked.connect(self.accept)
        content.addWidget(ok_button)

        self.setFixedSize(self.sizeHint())

class WrapperErrorDialog(QDialog):

    def __init__(self, error_excerpt: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wrapper Connection Issue")
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

      
        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(360)
        self.bg_widget.setStyleSheet("""
            QFrame {
                background-color: #2c2c2c;
                border-radius: 12px;
                border: 1px solid #444;
            }
            QLabel {
                background-color: transparent;
                border: none;
            }
            QLabel#Title { color: white; }
            QLabel#Body  { color: #b0b0b0; }
            QLabel#Hint  { color: #9aa0a6; font-size: 9pt; }
            QPlainTextEdit#Details {
                background-color: #1e1e1e;
                color: #c8c8c8;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 8pt;
            }
            QPushButton#Primary {
                background-color: #d60117;
                color: white;
                border: none;
                border-radius: 8px;
                height: 32px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton#Primary:hover { background-color: #e62237; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.bg_widget)

        content = QVBoxLayout(self.bg_widget)
        content.setContentsMargins(24, 18, 24, 18)
        content.setSpacing(12)

        title = QLabel("Can’t reach the wrapper")
        title.setObjectName("Title")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)

        body = QLabel("The selected wrapper is not responding.\nCheck its endpoint in Settings > Wrapper, then try again.")
        body.setObjectName("Body")
        bf = QFont(); bf.setPointSize(10)
        body.setFont(bf)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(body)

        steps = QLabel(
            "1) Make sure the wrapper is running.\n"
            "2) If it was running, check that it is still open. If it stopped, please start it again.\n"
            "3) If you see messages like “Invalid CKC” or “Playback error,” these are usually temporary.\n"
            "   Restarting the wrapper often fixes the problem."
        )
        steps.setObjectName("Body")
        steps.setFont(bf)
        steps.setWordWrap(True)
        steps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(steps)

        
        if error_excerpt:
            hint = QLabel("Errors received")
            hint.setObjectName("Hint")
            content.addWidget(hint)
            details = QPlainTextEdit(error_excerpt)
            details.setObjectName("Details")
            details.setReadOnly(True)
            details.setFixedHeight(96)
            details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            content.addWidget(details)

        content.addSpacing(15)


        close_btn = QPushButton("Close")
        close_btn.setObjectName("Primary")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        content.addWidget(close_btn)

        self.setFixedSize(self.sizeHint())

    def keyPressEvent(self, e):
       
        if e.key() == Qt.Key.Key_Escape:
            e.ignore()
            return
        super().keyPressEvent(e)

class UpdateDownloadSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


class UpdateDownloadTask(QRunnable):
    def __init__(self, session, asset, folder):
        super().__init__()
        self.session, self.asset, self.folder = session, asset, folder
        self.signals = UpdateDownloadSignals()

    def run(self):
        from core.controllers.updates import download
        try:
            target = download(self.session, self.asset, self.folder, self.signals.progress.emit)
            self.signals.finished.emit(str(target))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, release, current_version, session=None, parent=None):
        super().__init__(parent)
        self.release = release
        self.current_version = current_version
        self.session = session
        self.download_task = None
        self.downloaded = None
        self.setWindowTitle("Update Available")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(500)
        self.bg_widget.setStyleSheet("""
            QFrame {
                background-color: #2c2c2c;
                border-radius: 12px;
                border: 1px solid #444;
            }
            QLabel {
                background-color: transparent;
                border: none;
            }
            QLabel#Title { color: white; }
            QLabel#Body  { color: #b0b0b0; }
            QTextBrowser {
                background-color: #232323;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                color: #d0d0d0;
                padding: 6px;
            }
            QProgressBar {
                background-color: #232323;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                height: 8px;
            }
            QProgressBar::chunk { background-color: #d60117; border-radius: 4px; }
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px 12px;
                color: #e0e0e0;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a5a5a; }
            QPushButton:disabled { color: #8a8a8a; }
            QPushButton#Primary {
                background-color: #d60117;
                color: white;
            }
            QPushButton#Primary:hover { background-color: #e62237; }
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self.bg_widget)

        layout = QVBoxLayout(self.bg_widget)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Update Available")
        title.setObjectName("Title")
        title.setFont(QFont("Inter Tight", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        info = QLabel(f"apmyx <b>{release['version']}</b> is available. You have <b>{current_version}</b>.")
        info.setObjectName("Body")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)

        if release.get("notes"):
            notes = QTextBrowser()
            notes.setOpenExternalLinks(True)
            notes.setMarkdown(release["notes"])
            notes.setFixedHeight(200)
            layout.addWidget(notes)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Body")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.skip_btn = QPushButton("Skip This Version")
        self.skip_btn.clicked.connect(self.skip_version)
        self.later_btn = QPushButton("Remind Me Later")
        self.later_btn.clicked.connect(self.remind_later)
        self.page_btn = QPushButton("Release Page")
        self.page_btn.clicked.connect(self.open_releases)
        self.download_btn = QPushButton("Download")
        self.download_btn.setObjectName("Primary")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setVisible(bool(release.get("asset")) and session is not None)

        for button in (self.skip_btn, self.later_btn, self.page_btn, self.download_btn):
            btn_layout.addWidget(button)
        layout.addLayout(btn_layout)

        self.adjustSize()

    def skip_version(self):
        from core.controllers.updates import skip_version
        skip_version(self.release["version"])
        self.reject()

    def remind_later(self):
        from core.controllers.updates import snooze
        snooze()
        self.reject()

    def open_releases(self):
        webbrowser.open(self.release["url"])
        self.accept()

    def start_download(self):
        if self.downloaded:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.downloaded).parent)))
            return
        folder = Path.home() / "Downloads"
        if not folder.is_dir():
            folder = Path.home()
        self.download_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText(f"Downloading {self.release['asset']['name']}...")
        self.status.show()
        self.adjustSize()
        task = UpdateDownloadTask(self.session, self.release["asset"], folder)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_downloaded)
        task.signals.failed.connect(self._on_failed)
        self.download_task = task
        QThreadPool.globalInstance().start(task)

    def _on_progress(self, done, total):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _on_downloaded(self, path):
        self.downloaded = path
        verified = "SHA-256 verified. " if self.release["asset"].get("sha256") else ""
        self.status.setText(f"Saved to {path}. {verified}Close apmyx and extract it to update.")
        self.progress.hide()
        self.download_btn.setText("Show in Folder")
        self.download_btn.setEnabled(True)
        self.later_btn.setText("Close")
        self.later_btn.clicked.disconnect()
        self.later_btn.clicked.connect(self.reject)
        self.adjustSize()

    def _on_failed(self, message):
        self.status.setText(f"Download failed: {message}")
        self.progress.hide()
        self.download_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.adjustSize()

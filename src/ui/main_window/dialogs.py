from PyQt6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import webbrowser

class StorefrontRequiredDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
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
            "A storefront that matches your Apple Music account region must be set before searching. Please set one in Settings."
        )
        body.setObjectName("Body")
        bf = QFont(); bf.setPointSize(10)
        body.setFont(bf)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(body)

        content.addSpacing(15)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("Secondary")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)

        settings_button = QPushButton("Open Settings")
        settings_button.setObjectName("Primary")
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.clicked.connect(self.accept)

        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(settings_button)
        button_layout.addStretch()
        
        content.addLayout(button_layout)

        self.setFixedSize(self.sizeHint())

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

        # Title
        title = QLabel("Restart Required")
        title.setObjectName("Title")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)

        # Body
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

        # Title
        title = QLabel("Can’t reach the wrapper")
        title.setObjectName("Title")
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)

        # Body
        body = QLabel("The wrapper isn’t responding on 127.0.0.1:10020.\nFollow these steps, then try again.")
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
            hint = QLabel(error_excerpt)
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content.addWidget(hint)

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

class UpdateDialog(QDialog):
    def __init__(self, latest_version, current_version, release_url, parent=None):
        super().__init__(parent)
        self.latest_version = latest_version
        self.current_version = current_version
        self.release_url = release_url
        self.setWindowTitle("Update Available")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        self.bg_widget = QFrame(self)
        self.bg_widget.setFixedWidth(420)
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
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px 16px;
                color: #e0e0e0;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover { background-color: #5a5a5a; }
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
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Update Available")
        title.setObjectName("Title")
        title.setFont(QFont("Inter Tight", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        info_text = f"A new version <b>{self.latest_version}</b> is available!<br>Your version: <b>{self.current_version}</b><br><br>Visit the releases page to download the latest version."
        info = QLabel(info_text)
        info.setObjectName("Body")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        later_btn = QPushButton("Later")
        later_btn.clicked.connect(self.reject)

        open_btn = QPushButton("Open Releases")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self.open_releases)

        btn_layout.addStretch()
        btn_layout.addWidget(later_btn)
        btn_layout.addWidget(open_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.setFixedSize(self.sizeHint())

    def open_releases(self):
        webbrowser.open(self.release_url)
        self.accept()
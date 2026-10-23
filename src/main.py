try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import sys
import yaml
import logging
import os
import atexit
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont, QIcon
from core.app import AppController
from core.config import sync_storefront
from ui.main_window import MainWindow
from ui.main_window.dialogs import UpdateDialog 
from core.config import config_path, upgrade_config
from core.resources import app_dir
from core.logs import log_unhandled, setup_file_logging


APP_FONT_FAMILY = "Inter Tight"
APP_FALLBACK_FONTS = '"Segoe UI", "Helvetica Neue", "Arial", sans-serif'
APP_FONT = QFont(APP_FONT_FAMILY, 9)

APP_FONT = QFont(APP_FONT_FAMILY, 9)

APP_FONT.setHintingPreference(QFont.HintingPreference.PreferNoHinting)

APP_FONT.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)


FONT_FAMILY_STYLESHEET = f'font-family: "{APP_FONT_FAMILY}", {APP_FALLBACK_FONTS};'


DARK_STYLESHEET = f"""
    * {{
        {FONT_FAMILY_STYLESHEET}
    }}
    QWidget {{
        background-color: #1f1f1f;
        color: #e0e0e0;
    }}
    QMainWindow, QStatusBar {{
        background-color: #1f1f1f;
    }}
    QLineEdit {{
        background-color: #2e2e2e;
        border: 1px solid #444;
        border-radius: 4px;
        padding: 5px;
    }}
    QPushButton {{
        background-color: #4a4a4a;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 5px 10px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: #5a5a5a;
    }}
    QPushButton:pressed {{
        background-color: #6a6a6a;
    }}
    QComboBox {{
        background-color: #3c3c3c;
        border: 1px solid #555;
        border-radius: 4px;
        padding: 3px;
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QScrollArea {{
        background-color: #1f1f1f;
        border: none;
    }}
    QScrollBar:vertical {{
        border: none;
        background: #1f1f1f;
        width: 10px;
        margin: 0px 0px 0px 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #555;
        min-height: 20px;
        border-radius: 5px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QDockWidget {{
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background-color: #3c3c3c;
        text-align: center;
        padding: 5px;
    }}
"""

VERSION = "1.1.1"
REPO_OWNER = "rwnk-12"
REPO_NAME = "apmyx-gui"
RELEASES_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases"

def resource_path(relative_path):
    
    try:
        
        base_path = sys._MEIPASS
    except Exception:
    
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    return os.path.join(base_path, relative_path)

def setup_logging():

    handlers = [logging.StreamHandler(sys.stdout)] if sys.stdout else []
    logging.basicConfig(
        level=logging.INFO,
        format='[PYTHON] %(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers or [logging.NullHandler()],
        force=True,
    )
    setup_file_logging(VERSION)

    def handle_exception(exc_type, exc_value, exc_traceback):

        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        log_unhandled(exc_type, exc_value, exc_traceback, "main thread")
        QApplication.quit()

    sys.excepthook = handle_exception


def load_fonts():
  
    regular_font_path = resource_path('src/assets/Inter/Inter_Tight/InterTight-VariableFont_wght.ttf')
    italic_font_path = resource_path('src/assets/Inter/Inter_Tight/InterTight-Italic-VariableFont_wght.ttf')

    if os.path.exists(regular_font_path):
        if QFontDatabase.addApplicationFont(regular_font_path) == -1:
            logging.warning(f"Failed to load Inter Tight font from: {regular_font_path}")
        else:
            logging.info("Successfully loaded Inter Tight font.")
    else:
        logging.warning(f"Inter Tight font not found at: {regular_font_path}")
        
    if os.path.exists(italic_font_path):
        if QFontDatabase.addApplicationFont(italic_font_path) == -1:
            logging.warning(f"Failed to load Inter Tight Italic font from: {italic_font_path}")
        else:
            logging.info("Successfully loaded Inter Tight Italic font.")
    else:
        logging.warning(f"Inter Tight Italic font not found at: {italic_font_path}")


def load_config():
    
    default_storefront = 'us'
    try:
        with open(config_path(), 'r', encoding='utf-8') as f:
            config = sync_storefront(yaml.safe_load(f) or {})
            storefront = config.get('storefront', default_storefront)
            logging.info(f"Loaded storefront '{storefront}' from config.yaml")
            return storefront.lower()
    except FileNotFoundError:
        logging.warning("config.yaml not found. Using default storefront 'us'.")
        return default_storefront
    except Exception as e:
        logging.error(f"Error loading config.yaml: {e}. Using default storefront 'us'.")
        return default_storefront

def final_cleanup():
    logging.info("Final atexit cleanup triggered.")

    os._exit(0)

atexit.register(final_cleanup)

if __name__ == "__main__":
    tools = app_dir() / "tools"
    if tools.is_dir():
        os.environ["PATH"] = str(tools) + os.pathsep + os.environ.get("PATH", "")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    setup_logging()
    upgrade_config()

    app = QApplication(sys.argv)
    
    app.setOrganizationName("rwnk-12")
    app.setApplicationName("apmyx-gui")
    
    icon_path = resource_path('src/assets/icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        logging.info(f"Application icon set from {icon_path}")
    else:
        logging.warning(f"Application icon not found at: {icon_path}")

    load_fonts()

    app.setFont(APP_FONT)

    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)
    logging.info("Applied dark theme with #1f1f1f background color.")

    storefront = load_config()
    
  
    controller = AppController(storefront=storefront)
    
    controller.VERSION = VERSION
    controller.REPO_OWNER = REPO_OWNER
    controller.REPO_NAME = REPO_NAME
    controller.RELEASES_URL = RELEASES_URL

    window = MainWindow(controller)
    window.show()
    
    def handle_update(release):
        UpdateDialog(release, VERSION, controller.session, window).exec()

    controller.update_available.connect(handle_update)
    controller.checkforupdates()

    sys.exit(app.exec())

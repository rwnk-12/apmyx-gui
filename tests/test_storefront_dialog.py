import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow

app = QApplication.instance() or QApplication([])

from ui.main_window.dialogs import StorefrontRequiredDialog
from ui.main_window.mixins.search_features import SearchFeatures
from ui.main_window.window import MainWindow
from ui.settings_page import SettingsPage


class StorefrontDialogTests(unittest.TestCase):
    def test_typing_detect_and_save(self):
        dialog = StorefrontRequiredDialog()
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.save_button.isEnabled())
        QTest.keyClicks(dialog.code_input, "G")
        self.assertFalse(dialog.save_button.isEnabled())
        QTest.keyClicks(dialog.code_input, "B9x")
        self.assertEqual(dialog.code_input.text(), "gb")
        self.assertTrue(dialog.save_button.isEnabled())
        dialog._on_detect_failed("timeout")
        self.assertIn("Could not detect", dialog.hint.text())
        self.assertEqual(dialog.hint.objectName(), "Error")
        dialog._on_detected("FR")
        self.assertEqual(dialog.code_input.text(), "fr")
        self.assertIn("FR", dialog.hint.text())
        dialog._save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.storefront, "fr")
        for text in (dialog.hint.text(), "Could not detect your country. Type the code yourself."):
            self.assertNotIn(";", text)


class SaveStorefrontTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "config.yaml"
        self.config.write_text(yaml.safe_dump({"storefront": "", "wrapper": "applemusicdecrypt", "aac-type": "aac-lc"}), encoding="utf-8")
        patcher = patch("ui.main_window.window.config_path", return_value=self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = Mock()
        self.window.settings_page = Mock()

    def test_save_writes_config_and_applies_it_everywhere(self):
        self.assertTrue(MainWindow._save_storefront(self.window, "jp"))
        saved = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"storefront": "jp", "wrapper": "applemusicdecrypt", "aac-type": "aac-lc"})
        self.window.controller.apply_runtime_settings.assert_called_once_with(saved)
        self.window.settings_page.set_storefront.assert_called_once_with("jp")

    def test_failed_save_reports_and_changes_nothing(self):
        with patch("builtins.open", side_effect=PermissionError("denied")):
            self.assertFalse(MainWindow._save_storefront(self.window, "jp"))
        self.window.show_popup.assert_called_once()
        self.window.controller.apply_runtime_settings.assert_not_called()

    def test_settings_page_shows_the_new_storefront_without_unsaved_changes(self):
        parent = QMainWindow()
        self.addCleanup(parent.close)
        page = SettingsPage(str(self.config), parent)
        page._dirty = False
        page.set_storefront("jp")
        self.assertEqual(page.widgets["storefront"].text(), "jp")
        self.assertEqual(page.config["storefront"], "jp")
        self.assertFalse(page._dirty)


class SearchPromptTests(unittest.TestCase):
    def test_search_continues_after_saving_and_stops_after_cancel(self):
        window = Mock()
        window.controller.storefront = ""
        window.show_storefront_required_dialog.return_value = True
        self.assertTrue(SearchFeatures._ensure_storefront_or_prompt(window))
        window.show_storefront_required_dialog.return_value = False
        self.assertFalse(SearchFeatures._ensure_storefront_or_prompt(window))
        window.controller.storefront = "us"
        window.show_storefront_required_dialog.reset_mock()
        self.assertTrue(SearchFeatures._ensure_storefront_or_prompt(window))
        window.show_storefront_required_dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()

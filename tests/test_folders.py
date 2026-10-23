from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared import folders


class DefaultFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.downloads = Path(self.temp.name) / "D" / "My Downloads"
        self.downloads.mkdir(parents=True)
        (self.home / "Music").mkdir(parents=True)
        known = {"Downloads": self.downloads, "Music": self.home / "Music"}
        for target, value in (
            ("pathlib.Path.home", lambda: self.home),
            ("backend.shared.folders.known_folder", lambda name: known.get(name, self.home / name)),
        ):
            patcher = patch(target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_defaults_live_in_the_real_downloads_folder(self):
        self.assertEqual(folders.default_folders(), {
            "alac-save-folder": str(self.downloads / "apmyx" / "ALAC"),
            "aac-save-folder": str(self.downloads / "apmyx" / "AAC"),
            "atmos-save-folder": str(self.downloads / "apmyx" / "Atmos"),
            "mv-save-folder": str(self.downloads / "apmyx" / "Music Videos"),
        })

    def test_missing_downloads_falls_back_to_home(self):
        self.downloads.rmdir()
        self.assertEqual(folders.downloads_root(), self.home / "apmyx")

    def test_every_previous_default_moves_and_custom_folders_stay(self):
        config = {
            "alac-save-folder": str(self.home / "Music" / "apmyx-downloads" / "ALAC"),
            "aac-save-folder": "AM-DL-AAC downloads",
            "atmos-save-folder": str(self.home / "apmyx-downloads" / "Atmos"),
            "mv-save-folder": str(Path(self.temp.name) / "Mine" / "Videos"),
        }
        upgraded, changed = folders.upgrade_folders(config)
        self.assertTrue(changed)
        defaults = folders.default_folders()
        for key in ("alac-save-folder", "aac-save-folder", "atmos-save-folder"):
            self.assertEqual(upgraded[key], defaults[key])
            self.assertEqual(folders.save_folder(config, key), Path(defaults[key]).resolve())
        self.assertEqual(upgraded["mv-save-folder"], config["mv-save-folder"])
        self.assertEqual(folders.upgrade_folders(upgraded), (upgraded, False))

    def test_blocked_folder_hint_only_for_protected_folders_on_windows(self):
        music = str(self.home / "Music" / "apmyx-downloads" / "ALAC")
        blocked = f"Wrapper Lite downloaded 0 of 1 tracks. [WinError 2] The system cannot find the file specified: {music!r}"
        with patch.object(folders.sys, "platform", "win32"):
            hint = folders.blocked_folder_hint(blocked)
            self.assertIn("Controlled Folder Access", hint)
            self.assertIn("Music folder", hint)
            forward = f"[WinError 2] The system cannot find the file specified: '{Path(music).as_posix()}'"
            backward = f"[WinError 2] The system cannot find the file specified: '{music.replace('/', chr(92))}'"
            self.assertIn("Music folder", folders.blocked_folder_hint(forward))
            self.assertIn("Music folder", folders.blocked_folder_hint(backward))
            self.assertNotIn(";", hint)
            elsewhere = str(self.downloads / "apmyx" / "ALAC")
            self.assertEqual(folders.blocked_folder_hint(f"[WinError 2] The system cannot find the file specified: {elsewhere!r}"), "")
            self.assertEqual(folders.blocked_folder_hint("Wrapper Lite downloaded 0 of 1 tracks. Network error"), "")
        with patch.object(folders.sys, "platform", "darwin"):
            self.assertEqual(folders.blocked_folder_hint(blocked), "")


if __name__ == "__main__":
    unittest.main()

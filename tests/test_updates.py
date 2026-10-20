import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core.controllers import updates


def released_1_0_2_is_newer(latest, current):
    def parse_version(v):
        try:
            clean_v = (v or "0.0.0").split("-")[0]
            return tuple(map(int, clean_v.split(".")))
        except ValueError:
            return (0, 0, 0)

    return parse_version(latest) > parse_version(current)


def release(tag="v1.1.0", assets=None, body="Notes"):
    return {"tag_name": tag, "html_url": f"https://github.com/rwnk-12/apmyx-gui/releases/tag/{tag}",
            "body": body, "assets": assets or []}


class Controller(updates.UpdatesMixin):
    VERSION = "1.1.0"
    REPO_OWNER = "rwnk-12"
    REPO_NAME = "apmyx-gui"

    def __init__(self, data, status=200):
        self.session = MagicMock()
        self.session.get.return_value = MagicMock(status_code=status, json=lambda: data)
        self.update_available = MagicMock()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        state = patch.object(updates, "state_path", return_value=Path(self.folder.name, "update-state.json"))
        state.start()
        self.addCleanup(state.stop)
        config = patch.object(updates, "load_config", return_value={})
        self.config = config.start()
        self.addCleanup(config.stop)

    def test_next_release_tag_is_seen_by_the_released_1_0_2_client(self):
        tag = release()["tag_name"].lstrip("v")
        self.assertTrue(released_1_0_2_is_newer(tag, "1.0.2"))
        self.assertTrue(updates.is_newer(tag, "1.0.2"))
        self.assertEqual(updates.release_info(release())["version"], tag)

    def test_version_comparison(self):
        cases = [
            ("1.1.0", "1.0.2", True), ("v1.1.0", "1.0.2", True), ("1.0", "1.0.0", False),
            ("1.0.0", "1.0", False), ("1.1.0", "1.1.0-beta", True), ("1.1.0-beta", "1.1.0", False),
            ("1.2", "1.10", False), ("release-2", "1.0.0", False), ("", "1.0.0", False),
        ]
        for latest, current, expected in cases:
            with self.subTest(latest=latest, current=current):
                self.assertEqual(updates.is_newer(latest, current), expected)

    def test_windows_asset_and_digest_are_picked(self):
        assets = [
            {"name": "source.tar.gz", "browser_download_url": "u0", "size": 1},
            {"name": "apmyx-1.1.0-windows.zip", "browser_download_url": "u1", "size": 5,
             "digest": "sha256:" + "a" * 64},
            {"name": "apmyx-1.1.0-setup.exe", "browser_download_url": "u2", "size": 7},
        ]
        self.assertEqual(updates.pick_asset(assets)["name"], "apmyx-1.1.0-setup.exe")
        picked = updates.pick_asset(assets[:2])
        self.assertEqual((picked["name"], picked["sha256"]), ("apmyx-1.1.0-windows.zip", "a" * 64))
        self.assertIsNone(updates.pick_asset(assets[:1]))

    def test_check_emits_once_and_respects_cache_skip_snooze_and_setting(self):
        controller = Controller(release("v1.2.0"))
        controller._check_for_updates_worker()
        controller.update_available.emit.assert_called_once()
        self.assertEqual(controller.update_available.emit.call_args.args[0]["version"], "1.2.0")
        controller._check_for_updates_worker()
        self.assertEqual(controller.session.get.call_count, 1)
        updates.snooze()
        controller._check_for_updates_worker()
        self.assertEqual(controller.update_available.emit.call_count, 2)
        updates.save_state(snoozed_until=0)
        updates.skip_version("1.2.0")
        controller._check_for_updates_worker()
        self.assertEqual(controller.update_available.emit.call_count, 2)
        updates.save_state(skipped="")
        self.config.return_value = {"check-updates": False}
        controller._check_for_updates_worker()
        self.assertEqual(controller.update_available.emit.call_count, 2)

    def test_same_or_older_release_and_failures_stay_quiet(self):
        for data, status in ((release("v1.1.0"), 200), (release("v1.0.2"), 200), ({}, 403)):
            with self.subTest(status=status, tag=data.get("tag_name")):
                updates.save_state(checked_at=0, release=None)
                controller = Controller(data, status)
                controller._check_for_updates_worker()
                controller.update_available.emit.assert_not_called()

    def test_download_verifies_the_published_sha256(self):
        payload = b"apmyx release"
        good = {"name": "apmyx.zip", "url": "u", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload[:5], payload[5:]]
        session = MagicMock()
        session.get.return_value = response
        folder = Path(self.folder.name)
        progress = []
        target = updates.download(session, good, folder, lambda done, total: progress.append((done, total)))
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(progress[-1], (len(payload), len(payload)))
        bad = dict(good, name="bad.zip", sha256="0" * 64)
        with self.assertRaises(ValueError):
            updates.download(session, bad, folder)
        self.assertFalse((folder / "bad.zip").exists())
        self.assertFalse((folder / "bad.zip.partial").exists())

    def test_dialog_offers_download_skip_and_later(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from ui.main_window.dialogs import UpdateDialog

        app = QApplication.instance() or QApplication([])
        info = updates.release_info(release("v1.2.0", [{"name": "apmyx.zip", "browser_download_url": "u", "size": 3}]))
        dialog = UpdateDialog(info, "1.1.0", MagicMock())
        self.assertFalse(dialog.download_btn.isHidden())
        dialog.skip_version()
        self.assertEqual(json.loads(updates.state_path().read_text())["skipped"], "1.2.0")
        no_asset = UpdateDialog(updates.release_info(release("v1.2.0")), "1.1.0", MagicMock())
        self.assertTrue(no_asset.download_btn.isHidden())
        no_asset.remind_later()
        self.assertGreater(json.loads(updates.state_path().read_text())["snoozed_until"], time.time())
        dialog.close()
        no_asset.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()

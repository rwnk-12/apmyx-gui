import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core import wrapper_lite


def completed(code, stdout="", stderr=""):
    def run(command, **kwargs):
        assert kwargs["stdout"] not in (subprocess.PIPE, None), "launcher output must not use a pipe"
        assert kwargs["stderr"] == subprocess.STDOUT and "capture_output" not in kwargs
        kwargs["stdout"].write((stdout + stderr).encode("utf-8"))
        return subprocess.CompletedProcess(command, code)
    return run


class WrapperLiteGuiTests(unittest.TestCase):
    def setUp(self):
        wrapper_lite.started_by_app = False
        self.addCleanup(setattr, wrapper_lite, "started_by_app", False)

    def test_only_local_http_urls_are_managed(self):
        self.assertEqual(wrapper_lite.local_port("http://127.0.0.1:12340"), 12340)
        self.assertEqual(wrapper_lite.local_port("http://localhost:23450/"), 23450)
        for url in ("https://wrapper.example.com", "http://192.168.1.5:12340", "", "not a url"):
            self.assertIsNone(wrapper_lite.local_port(url))

    def test_commands_call_the_existing_launchers(self):
        with patch.object(wrapper_lite.sys, "platform", "win32"):
            windows = wrapper_lite.command("start", 12340)
        self.assertEqual(windows[:5], ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File"])
        self.assertTrue(windows[5].endswith("setup-qemu.ps1"))
        self.assertEqual(windows[6:], ["-Action", "Start", "-HttpPort", "12340"])
        self.assertNotIn("Bypass", " ".join(windows))
        with patch.object(wrapper_lite.sys, "platform", "darwin"):
            posix = wrapper_lite.command("stop", 23450)
        self.assertTrue(posix[1].endswith("setup-wrapper-lite-qemu.sh"))
        self.assertEqual(posix[2:], ["--action", "stop", "--http-port", "23450"])

    def test_messages_are_cleaned_for_the_status_line(self):
        ok = completed(0, "[03:06:18] Wrapper Lite QEMU is ready at http://127.0.0.1:12340. You can close this window.\n")
        with patch("subprocess.run", side_effect=ok):
            self.assertEqual(wrapper_lite.run("start", 12340), (True, "Wrapper Lite QEMU is ready at http://127.0.0.1:12340."))
        docker = completed(0, "[03:06:18] QEMU could not start Wrapper Lite on this PC: QEMU exited during startup.\n"
                              "[03:06:19] Switching Wrapper Lite to Docker. This only happens once.\n"
                              "[03:07:02] Wrapper Lite is ready in Docker at http://127.0.0.1:12340. You can close this window.\n"
                              "Select AppleMusicDecrypt or Wrapper Lite in GUI Settings > Wrapper.\n")
        with patch("subprocess.run", side_effect=docker):
            self.assertEqual(wrapper_lite.run("start", 12340), (True, "Wrapper Lite is ready in Docker at http://127.0.0.1:12340."))
        failed = completed(1, "", "Setup failed: Wrapper Lite has no authenticated session. Use -Action Login.\n")
        with patch("subprocess.run", side_effect=failed):
            self.assertEqual(wrapper_lite.run("start", 12340), (False, "Wrapper Lite has no authenticated session. Use -Action Login."))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertFalse(wrapper_lite.run("stop", 12340)[0])

    def test_exit_stops_only_a_wrapper_this_session_started(self):
        ok = completed(0, "Wrapper Lite QEMU is running at http://127.0.0.1:12340.\n")
        with patch("subprocess.Popen") as popen:
            with patch.object(wrapper_lite, "running", return_value=True), patch("subprocess.run", side_effect=ok):
                self.assertTrue(wrapper_lite.start(12340)[0])
            self.assertFalse(wrapper_lite.stop_if_started(12340))
            popen.assert_not_called()
            with patch.object(wrapper_lite, "running", return_value=False), patch("subprocess.run", side_effect=ok):
                wrapper_lite.start(12340)
            self.assertTrue(wrapper_lite.stop_if_started(12340))
            self.assertIn("stop", " ".join(popen.call_args.args[0]).lower())
        with patch("subprocess.run", side_effect=ok):
            wrapper_lite.stop(12340)
        self.assertFalse(wrapper_lite.started_by_app)

    def test_installed_and_running_read_the_launcher_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "backend/wrapper-runtime/wrapper-lite-qemu"
            runtime.mkdir(parents=True)
            (root / "scripts/wrappers").mkdir(parents=True)
            with patch.object(wrapper_lite, "app_root", return_value=root):
                self.assertFalse(wrapper_lite.installed())
                (runtime / "installed.json").write_text("{}", encoding="utf-8")
                (root / "scripts/wrappers/setup-qemu.ps1").write_text("", encoding="utf-8")
                (root / "scripts/wrappers/setup_qemu.py").write_text("", encoding="utf-8")
                self.assertTrue(wrapper_lite.installed())
                self.assertFalse(wrapper_lite.running())
                (runtime / "process.json").write_text(json.dumps({"pid": 4242}), encoding="utf-8-sig")
                with patch("psutil.pid_exists", return_value=True):
                    self.assertTrue(wrapper_lite.running())


    def test_settings_controls_any_local_wrapper(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(ROOT))
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from core import wrapper_control
        from core.workers import wrapper_pool
        from ui.settings_page import SettingsPage

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp, patch.object(wrapper_control, "detect") as detect:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "config.yaml"), parent)
            wrapper = page.widgets["wrapper"]
            url = page.widgets["applemusicdecrypt-url"]
            wrapper.setCurrentIndex(wrapper.findData("applemusicdecrypt"))
            url.setText("http://127.0.0.1:12340")
            page._update_lite_controls()
            self.assertFalse(page.lite_controls.isHidden())
            url.setText("https://wrapper.example.com")
            self.assertTrue(page.lite_controls.isHidden())
            url.setText("http://127.0.0.1:12340")
            wrapper.setCurrentIndex(wrapper.findData("legacy"))
            self.assertFalse(page.lite_controls.isHidden())

            running = wrapper_control.State("applemusicdecrypt", 12340, running="docker", detail="Docker container apmyx-wrapper-lite",
                                            stop_plan=("docker", "apmyx-wrapper-lite"),
                                            message="Wrapper Lite is running (Docker container apmyx-wrapper-lite).")
            detect.return_value = running
            wrapper.setCurrentIndex(wrapper.findData("applemusicdecrypt"))
            page._detect_lite()
            wrapper_pool().waitForDone(5000)
            app.processEvents()
            self.assertEqual(page.lite_stop.text(), "Stop Wrapper Lite")
            self.assertTrue(page.lite_stop.isEnabled())
            self.assertTrue(page.lite_start.isEnabled())
            self.assertIn("Docker container apmyx-wrapper-lite", page.lite_hint.text())

            from ui.settings_page import LITE_BUTTON_COLORS
            green, red = LITE_BUTTON_COLORS["start"], LITE_BUTTON_COLORS["stop"]
            self.assertIn(green["background"], page.lite_start.styleSheet())
            self.assertIn(f"QPushButton:hover {{ background-color: {green['hover']}; }}", page.lite_start.styleSheet())
            self.assertEqual(page.lite_stop.styleSheet(), "")
            page._apply_lite_state(wrapper_control.State("applemusicdecrypt", 12340, start_plan=("docker", "apmyx-wrapper-lite")))
            self.assertEqual(page.lite_start.styleSheet(), "")
            self.assertIn(red["background"], page.lite_stop.styleSheet())
            self.assertIn(f"QPushButton:hover {{ background-color: {red['hover']}; }}", page.lite_stop.styleSheet())
            page._apply_lite_state(wrapper_control.State("applemusicdecrypt", 12340, message="not set up"))
            self.assertEqual((page.lite_start.styleSheet(), page.lite_stop.styleSheet()), ("", ""))
            page._apply_lite_state(running)

            import threading
            release = threading.Event()
            calls = []

            def slow_start(state):
                calls.append(state)
                release.wait(5)
                return None, "Wrapper Lite is already running (Docker container apmyx-wrapper-lite)."

            with patch.object(wrapper_control, "start", side_effect=slow_start), patch("logging.error") as log_error:
                page._run_lite_action("start")
                for _ in range(5):
                    page._run_lite_action("start")
                self.assertEqual(page.lite_hint.text(), "Wrapper Lite is already starting, please wait.")
                self.assertTrue(page.lite_start.isEnabled() and page.lite_stop.isEnabled())
                release.set()
                wrapper_pool().waitForDone(5000)
                app.processEvents()
                self.assertEqual(len(calls), 1)
                self.assertIn("already running", page.wrapper_status.text())
                log_error.assert_not_called()
            wrapper_pool().waitForDone(5000)
            app.processEvents()

            detect.return_value = wrapper_control.State("legacy", 10020, message="older")
            page._detect_lite()
            page._lite_generation += 1
            page._apply_lite_state(wrapper_control.State("legacy", 10020, message="newer"))
            wrapper_pool().waitForDone(5000)
            app.processEvents()
            self.assertEqual(page.lite_hint.text(), "newer")
            self.assertEqual(page.lite_start.text(), "Start Legacy wrapper")

            page.begin_close()
            detect.return_value = wrapper_control.State("legacy", 10020, message="after close")
            page._detect_lite()
            wrapper_pool().waitForDone(5000)
            app.processEvents()
            self.assertEqual(page.lite_hint.text(), "newer")
            parent.close()
            app.processEvents()

    def test_closing_waits_for_a_wrapper_action_but_never_forever(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(ROOT))
        from PyQt6.QtWidgets import QApplication
        from ui.main_window.window import MainWindow

        app = QApplication.instance() or QApplication([])
        page = Mock()
        page.lite_busy.side_effect = [True, True, True, False, False]
        owner = Mock(settings_page=page)
        with patch("time.sleep"):
            MainWindow._finish_wrapper_action(owner, timeout=30)
        page.begin_close.assert_called_once()
        self.assertEqual(page.lite_busy.call_count, 5)

        stuck = Mock()
        stuck.lite_busy.return_value = True
        with patch("logging.warning") as warning:
            started = __import__("time").monotonic()
            MainWindow._finish_wrapper_action(Mock(settings_page=stuck), timeout=0.2)
            self.assertLess(__import__("time").monotonic() - started, 2)
        warning.assert_called_once()
        stuck.begin_close.assert_called_once()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()

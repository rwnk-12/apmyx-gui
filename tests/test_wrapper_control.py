import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core import wrapper_control, wrapper_lite

LITE = {"applemusicdecrypt-url": "http://127.0.0.1:12340"}


def inspect_line(name, running, port, finished="2026-10-20T10:00:00Z"):
    bindings = json.dumps({f"{port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]})
    return f"/{name}|{'true' if running else 'false'}|{bindings}|2026-10-20T09:00:00Z|{finished}"


def fake_docker(*lines):
    def run(*args, timeout=30):
        if args[:2] == ("ps", "-a"):
            return 0, "\n".join(line.split("|")[0].lstrip("/") for line in lines)
        if args[0] == "inspect":
            return 0, "\n".join(lines)
        return 0, ""
    return run


def qemu(pid, port, monitor):
    process = Mock(pid=pid)
    process.info = {"name": "qemu-system-x86_64.exe", "cmdline": [
        "qemu-system-x86_64.exe", "-nic", f"user,model=e1000,hostfwd=tcp:127.0.0.1:{port}-:12340",
        "-qmp", f"tcp:127.0.0.1:{monitor},server=on,wait=off"]}
    return process


class WrapperControlTests(unittest.TestCase):
    def setUp(self):
        wrapper_control.started.clear()
        self.addCleanup(wrapper_control.started.clear)
        for target, value in ((wrapper_lite, "installed"), (wrapper_lite, "running")):
            patcher = patch.object(target, value, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def detect(self, wrapper="applemusicdecrypt", settings=LITE, docker=None, processes=(), port_open=False):
        with patch.object(wrapper_control, "docker", side_effect=docker or fake_docker()), \
                patch.object(wrapper_control, "docker_cli", return_value="docker"), \
                patch("psutil.process_iter", return_value=list(processes)), \
                patch.object(wrapper_control, "port_open", return_value=port_open):
            return wrapper_control.detect(wrapper, settings)

    def test_endpoints_for_every_wrapper(self):
        self.assertEqual(wrapper_control.endpoint("applemusicdecrypt", LITE), 12340)
        self.assertIsNone(wrapper_control.endpoint("applemusicdecrypt", {"applemusicdecrypt-url": "https://wm.example.com"}))
        self.assertEqual(wrapper_control.endpoint("wrapper-v2", {"wrapper-v2-url": "http://127.0.0.1"}), 80)
        self.assertEqual(wrapper_control.endpoint("legacy", {"decrypt-m3u8-port": "127.0.0.1:10020"}), 10020)
        self.assertIsNone(wrapper_control.endpoint("legacy", {"decrypt-m3u8-port": "192.168.1.5:10020"}))
        self.assertIsNone(wrapper_control.detect("applemusicdecrypt", {"applemusicdecrypt-url": "https://x.example"}).port)

    def test_running_docker_container_is_stoppable_whoever_started_it(self):
        state = self.detect(docker=fake_docker(inspect_line("apmyx-wrapper-lite", True, 12340)), port_open=True)
        self.assertEqual((state.running, state.stop_plan, state.start_plan), ("docker", ("docker", "apmyx-wrapper-lite"), None))
        self.assertIn("Docker container apmyx-wrapper-lite", state.message)
        other = self.detect("wrapper-v2", {"wrapper-v2-url": "http://127.0.0.1"},
                            docker=fake_docker(inspect_line("my-own-v2", True, 80)), port_open=True)
        self.assertEqual(other.stop_plan, ("docker", "my-own-v2"))

    def test_qemu_from_this_folder_another_folder_or_unknown(self):
        own = qemu(111, 12340, 64403)
        with patch.object(wrapper_lite, "running", return_value=True), \
                patch("pathlib.Path.read_text", return_value=json.dumps({"pid": 111})):
            state = self.detect(processes=[own], port_open=True)
        self.assertEqual(state.stop_plan, ("launcher",))
        elsewhere = self.detect(processes=[qemu(222, 12340, 50000), qemu(333, 23450, 50001)], port_open=True)
        self.assertEqual(elsewhere.stop_plan, ("qmp", 222, 50000))
        self.assertIn("outside this apmyx folder", elsewhere.message)
        unknown = self.detect(port_open=True)
        self.assertEqual((unknown.running, unknown.stop_plan), ("other", None))
        self.assertIn("stop it where you started it", unknown.message)

    def test_start_uses_the_most_recently_used_install(self):
        docker = fake_docker(inspect_line("apmyx-wrapper-lite", False, 12340, finished="2026-10-22T10:00:00Z"))
        with patch.object(wrapper_lite, "installed", return_value=True), patch.object(wrapper_control, "launcher_last_used", return_value=0.0):
            self.assertEqual(self.detect(docker=docker).start_plan, ("docker", "apmyx-wrapper-lite"))
        with patch.object(wrapper_lite, "installed", return_value=True), patch.object(wrapper_control, "launcher_last_used", return_value=4102444800.0):
            state = self.detect(docker=docker)
            self.assertEqual(state.start_plan, ("launcher",))
            self.assertIn("Start uses QEMU", state.message)

    def test_nothing_installed_explains_what_to_do(self):
        state = self.detect()
        self.assertIsNone(state.start_plan)
        self.assertIn("setup-wrapper-lite-qemu", state.message)
        down = self.detect("legacy", {"decrypt-m3u8-port": "127.0.0.1:10020"}, docker=lambda *a, **k: (1, "engine down"))
        self.assertIn("Docker Desktop isn't running", down.message)
        for text in (state.message, down.message):
            self.assertNotIn(";", text)

    def test_docker_start_stop_and_exit_stops_only_what_this_session_started(self):
        stopped = wrapper_control.State("applemusicdecrypt", 12340, start_plan=("docker", "apmyx-wrapper-lite"))
        with patch.object(wrapper_control, "docker", return_value=(0, "apmyx-wrapper-lite")) as docker, \
                patch.object(wrapper_control, "wait_until_answering", return_value=True):
            self.assertTrue(wrapper_control.start(stopped)[0])
            docker.assert_called_with("start", "apmyx-wrapper-lite", timeout=120)
        self.assertIn("applemusicdecrypt", wrapper_control.started)
        with patch.object(wrapper_control, "docker_cli", return_value="docker"), patch("subprocess.Popen") as popen:
            self.assertEqual(wrapper_control.stop_started(), ["applemusicdecrypt"])
            self.assertEqual(popen.call_args.args[0], ["docker", "stop", "apmyx-wrapper-lite"])
            self.assertEqual(wrapper_control.stop_started(), [])
        running = wrapper_control.State("applemusicdecrypt", 12340, running="docker", stop_plan=("docker", "apmyx-wrapper-lite"))
        with patch.object(wrapper_control, "docker", return_value=(0, "")) as docker:
            self.assertTrue(wrapper_control.stop(running)[0])
            docker.assert_called_with("stop", "apmyx-wrapper-lite", timeout=120)

    def test_exit_also_stops_a_start_that_is_still_in_flight(self):
        wrapper_control.pending["applemusicdecrypt"] = (("launcher",), 12340)
        wrapper_control.pending["legacy"] = (("docker", "apmyx-legacy"), 10020)
        with patch.object(wrapper_control, "docker_cli", return_value="docker"), patch("subprocess.Popen") as popen:
            self.assertEqual(sorted(wrapper_control.stop_started()), ["applemusicdecrypt", "legacy"])
        commands = [" ".join(call.args[0]).lower() for call in popen.call_args_list]
        self.assertTrue(any("stop" in command and "12340" in command for command in commands))
        self.assertIn("docker stop apmyx-legacy", commands)
        self.assertEqual(wrapper_control.pending, {})

        failing = wrapper_control.State("applemusicdecrypt", 12340, start_plan=("docker", "apmyx-wrapper-lite"))
        with patch.object(wrapper_control, "docker", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                wrapper_control.start(failing)
        self.assertEqual(wrapper_control.pending, {})

    def test_repeated_start_or_stop_is_harmless(self):
        running = wrapper_control.State("applemusicdecrypt", 12340, running="docker", detail="Docker container apmyx-wrapper-lite",
                                        stop_plan=("docker", "apmyx-wrapper-lite"))
        stopped = wrapper_control.State("applemusicdecrypt", 12340, start_plan=("docker", "apmyx-wrapper-lite"))
        nothing = wrapper_control.State("legacy", 10020, message="No Legacy wrapper install was found.")
        with patch.object(wrapper_control, "docker") as docker, patch.object(wrapper_lite, "start") as launcher:
            self.assertEqual(wrapper_control.start(running), (None, "Wrapper Lite is already running (Docker container apmyx-wrapper-lite)."))
            self.assertEqual(wrapper_control.stop(stopped), (None, "Wrapper Lite is already stopped."))
            self.assertEqual(wrapper_control.start(nothing), (None, "No Legacy wrapper install was found."))
            docker.assert_not_called()
            launcher.assert_not_called()
        self.assertEqual(wrapper_control.started, {})

    def test_qemu_outside_this_folder_is_shut_down_through_its_monitor(self):
        state = wrapper_control.State("applemusicdecrypt", 12340, running="qemu", stop_plan=("qmp", 222, 50000))
        with patch.object(wrapper_control, "qmp_shutdown") as shutdown, patch("psutil.Process") as process:
            self.assertTrue(wrapper_control.stop(state)[0])
            shutdown.assert_called_once_with(50000)
            process.return_value.wait.assert_called_once_with(90)

    def test_windows_uses_docker_exe_not_the_bash_shim(self):
        with patch.object(wrapper_control.sys, "platform", "win32"), patch("shutil.which", return_value=None) as which:
            wrapper_control.docker_cli()
            which.assert_called_with("docker.exe")

    def test_docker_times_compare_with_local_file_times(self):
        self.assertEqual(wrapper_control.timestamp("0001-01-01T00:00:00Z"), 0.0)
        self.assertAlmostEqual(wrapper_control.timestamp("2026-10-23T12:03:30.926732683Z"), 1792757010.926732, places=3)


if __name__ == "__main__":
    unittest.main()

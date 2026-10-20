import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "wrappers"))
import setup_qemu


class WrapperLiteQemuPosixTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_platforms_map_to_pinned_upstream_packages(self):
        cases = {
            ("Linux", "x86_64"): "linux-x86_64", ("Linux", "aarch64"): "linux-aarch64",
            ("Darwin", "arm64"): "macos-aarch64",
        }
        for (system, machine), key in cases.items():
            with patch("platform.system", return_value=system), patch("platform.machine", return_value=machine):
                self.assertEqual(setup_qemu.platform_key(), key)
                package = setup_qemu.source()[1]
                self.assertRegex(package["sha256"], "^[a-f0-9]{64}$")
                self.assertGreater(package["size"], 0)
        for system, machine in (("Darwin", "x86_64"), ("Windows", "AMD64")):
            with patch("platform.system", return_value=system), patch("platform.machine", return_value=machine):
                with self.assertRaises(setup_qemu.SetupError):
                    setup_qemu.platform_key()

    def test_initramfs_appends_our_init_like_the_windows_launcher(self):
        original = self.root / "original.cpio.gz"
        original.write_bytes(gzip.compress(b"upstream-cpio"))
        output = self.root / "apmyx.cpio.gz"
        setup_qemu.build_initramfs(original, ROOT / "scripts/wrappers/qemu/init", output)
        content = gzip.decompress(output.read_bytes())
        self.assertTrue(content.startswith(b"upstream-cpio070701"))
        self.assertIn(b"init\0", content)
        self.assertIn(b"TRAILER!!!\0", content)
        self.assertNotIn(b"\r\n", content[len(b"upstream-cpio"):])
        if sys.platform != "win32":
            return
        windows = self.root / "windows.cpio.gz"
        script = (
            f"Import-Module '{ROOT / 'scripts/wrappers/modules/Qemu.psm1'}' -Force; "
            f"New-QemuInitramfs -Original '{original}' -InitScript '{ROOT / 'scripts/wrappers/qemu/init'}' -Destination '{windows}'"
        )
        runner = self.root / "run.ps1"
        runner.write_text(script, encoding="utf-8")
        subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-File", str(runner)], check=True, capture_output=True)
        self.assertEqual(content, gzip.decompress(windows.read_bytes()))

    def test_extract_rejects_escaping_paths_and_restores_exec_bits(self):
        archive = self.root / "package.zip"
        with zipfile.ZipFile(archive, "w") as package:
            executable = zipfile.ZipInfo("qemu/bin/qemu-system-x86_64")
            executable.external_attr = 0o100755 << 16
            package.writestr(executable, b"binary")
            package.writestr("qemu/data.img", b"disk")
        setup_qemu.extract(archive, self.root / "out")
        binary = self.root / "out/qemu/bin/qemu-system-x86_64"
        self.assertEqual(binary.read_bytes(), b"binary")
        if os.name == "posix":
            self.assertTrue(os.access(binary, os.X_OK))
            self.assertFalse(os.access(self.root / "out/qemu/data.img", os.X_OK))
        evil = self.root / "evil.zip"
        with zipfile.ZipFile(evil, "w") as package:
            package.writestr("../escaped.txt", b"x")
        with self.assertRaises(setup_qemu.SetupError):
            setup_qemu.extract(evil, self.root / "evil-out")
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_failed_verification_removes_the_partial_download(self):
        source = self.root / "source.bin"
        source.write_bytes(b"payload")
        target = self.root / "package.zip"
        with self.assertRaises(setup_qemu.SetupError):
            setup_qemu.download(source.as_uri(), target, "0" * 64, len(b"payload"))
        self.assertFalse(target.exists())
        self.assertFalse(target.with_name(target.name + ".partial").exists())
        setup_qemu.download(source.as_uri(), target, hashlib.sha256(b"payload").hexdigest(), len(b"payload"))
        self.assertEqual(target.read_bytes(), b"payload")

    @patch("platform.system", return_value="Linux")
    def test_qemu_runs_on_loopback_without_credentials(self, _system):
        service = setup_qemu.qemu_arguments(12340, 23451, "tcg")
        joined = " ".join(service)
        self.assertIn("user,model=e1000,hostfwd=tcp:127.0.0.1:12340-:12340", service)
        self.assertIn("tcp:127.0.0.1:23451,server=on,wait=off", service)
        self.assertEqual(service[service.index("-cpu") + 1], "max")
        self.assertNotRegex(joined, "apmyx_login=1|--login|password")
        login = setup_qemu.qemu_arguments(12340, 23451, "kvm", login=True, serial_port=23452)
        self.assertIn("tcp:127.0.0.1:23452,server=on,wait=on", login)
        self.assertIn("apmyx_login=1", " ".join(login))
        self.assertEqual(login[login.index("-cpu") + 1], "host")
        self.assertNotIn("password", " ".join(login))

    def test_macos_uses_homebrew_qemu_and_explains_when_missing(self):
        with patch("platform.system", return_value="Darwin"):
            with patch("shutil.which", return_value="/opt/homebrew/bin/qemu-system-x86_64"):
                arguments = setup_qemu.qemu_arguments(12340, 23451, "tcg")
                self.assertEqual(Path(arguments[0]), Path("/opt/homebrew/bin/qemu-system-x86_64"))
                self.assertNotIn("-L", arguments)
            with patch("shutil.which", return_value=None), patch("os.access", return_value=False):
                with self.assertRaisesRegex(setup_qemu.SetupError, "brew install qemu"):
                    setup_qemu.qemu_binary()


if __name__ == "__main__":
    unittest.main()

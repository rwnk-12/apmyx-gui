import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_backends


class BuildBackendTests(unittest.TestCase):
    def test_build_environment_finds_cargo_in_home_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cargo_bin = home / ".cargo" / "bin"
            cargo_bin.mkdir(parents=True)
            cargo = cargo_bin / ("cargo.exe" if os.name == "nt" else "cargo")
            cargo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            if os.name != "nt":
                cargo.chmod(0o755)
            original_path = str(home / "bin")
            with patch.object(build_backends.Path, "home", return_value=home):
                with patch.dict(os.environ, {"PATH": original_path}, clear=False):
                    env = build_backends.build_environment()

            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(cargo_bin))
            self.assertEqual(env["PATH"].split(os.pathsep)[1], original_path)

    def test_build_environment_preserves_cargo_already_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            cargo = path / ("cargo.exe" if os.name == "nt" else "cargo")
            cargo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            if os.name != "nt":
                cargo.chmod(0o755)
            with patch.dict(os.environ, {"PATH": str(path)}, clear=False):
                env = build_backends.build_environment()

        self.assertEqual(env["PATH"], str(path))


if __name__ == "__main__":
    unittest.main()

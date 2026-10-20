import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PROVIDERS = BACKEND / "providers"


def run(args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def package_data(package):
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.suffix not in {".py", ".pyc"} and "__pycache__" not in path.parts:
            yield path, Path(package.name, path.parent.relative_to(package)).as_posix()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args()
    suffix = ".exe" if sys.platform == "win32" else ""
    output = PROVIDERS / "legacy" / "bin" / ("downloader" + suffix)
    output.parent.mkdir(exist_ok=True)
    run(["go", "build", "-trimpath", "-o", output, "."], cwd=PROVIDERS / "legacy")
    runtime = BACKEND / "runtime"
    runtime.mkdir(exist_ok=True)
    lock = BACKEND / "runtime-requirements.txt"
    if lock.exists():
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--target",
                runtime,
                "-r",
                lock,
            ]
        )
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-deps",
                "--target",
                runtime,
                PROVIDERS / "gamdl",
            ]
        )
    else:
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--target",
                runtime,
                PROVIDERS / "gamdl",
                "psutil==7.2.2",
                "pyinstaller==6.22.3",
            ]
        )
    run([sys.executable, "-c", "from backend.router.applemusicdecrypt import check_native; check_native()"], cwd=ROOT)
    if args.bundle:
        env = {**os.environ, "PYTHONPATH": str(runtime)}
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "bridge",
            "--distpath",
            BACKEND / "bin",
            "--workpath",
            ROOT / "build" / "bridge",
            "--specpath",
            ROOT / "build",
            "--paths",
            BACKEND,
            "--paths",
            runtime,
            "--paths",
            PROVIDERS / "applemusicdecrypt",
            "--collect-all",
            "gamdl",
            "--collect-all",
            "psutil",
            "--collect-all",
            "applemusicdecrypt",
            "--collect-all",
            "temari",
            "--copy-metadata",
            "creart",
            "--add-data",
            str(PROVIDERS / "applemusicdecrypt" / "LICENSE.txt") + os.pathsep + "applemusicdecrypt",
            "--hidden-import",
            "router.legacy",
            "--hidden-import",
            "router.gamdl",
            "--hidden-import",
            "router.applemusicdecrypt",
            "--hidden-import",
            "yaml",
        ]
        for source, target in package_data(PROVIDERS / "applemusicdecrypt" / "applemusicdecrypt"):
            command += ["--add-data", str(source) + os.pathsep + target]
        command += [
            "--add-binary",
            str(PROVIDERS / "legacy" / "bin" / ("downloader" + suffix))
            + os.pathsep
            + "providers/legacy/bin",
        ]
        command += [BACKEND / "bridge.py"]
        run(command, env=env, cwd=ROOT)


if __name__ == "__main__":
    main()

from pathlib import Path


def asset_path(name):
    return Path(__file__).resolve().parent / "assets" / name

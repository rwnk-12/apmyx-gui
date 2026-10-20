from pathlib import Path


OLD_DEFAULTS = {
    "alac-save-folder": "AM-DL downloads",
    "aac-save-folder": "AM-DL-AAC downloads",
    "atmos-save-folder": "AM-DL-Atmos downloads",
    "mv-save-folder": "AM-DL downloads/Music Videos",
}


def downloads_root():
    music = Path.home() / "Music"
    return (music if music.is_dir() else Path.home()) / "apmyx-downloads"


def default_folders():
    root = downloads_root()
    return {
        "alac-save-folder": str(root / "ALAC"),
        "aac-save-folder": str(root / "AAC"),
        "atmos-save-folder": str(root / "Atmos"),
        "mv-save-folder": str(root / "Music Videos"),
    }


def save_folder(settings, key):
    value = settings.get(key)
    if not value or value == OLD_DEFAULTS[key]:
        value = default_folders()[key]
    return Path(value).resolve()


def upgrade_folders(config):
    defaults = default_folders()
    changed = {key: defaults[key] for key, old in OLD_DEFAULTS.items() if config.get(key) == old}
    return {**config, **changed}, bool(changed)


def save_folders(settings):
    return [save_folder(settings, key) for key in default_folders()]

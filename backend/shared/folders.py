import os
from pathlib import Path
import sys


SUBFOLDERS = {
    "alac-save-folder": "ALAC",
    "aac-save-folder": "AAC",
    "atmos-save-folder": "Atmos",
    "mv-save-folder": "Music Videos",
}
RELATIVE_DEFAULTS = {
    "alac-save-folder": "AM-DL downloads",
    "aac-save-folder": "AM-DL-AAC downloads",
    "atmos-save-folder": "AM-DL-Atmos downloads",
    "mv-save-folder": "AM-DL downloads/Music Videos",
}
KNOWN_FOLDERS = {
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Favorites": "1777F761-68AD-4D8A-87BD-30B759FA33DD",
}
PROTECTED = ("Documents", "Music", "Pictures", "Videos", "Desktop", "Favorites")
BLOCK_MARKERS = ("[WinError 2]", "[WinError 5]", "Access is denied", "cannot find the file specified")


def known_folder(name):
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            guid = GUID.from_buffer_copy(uuid.UUID(KNOWN_FOLDERS[name]).bytes_le)
            path = ctypes.c_wchar_p()
            shell32 = ctypes.WinDLL("shell32")
            shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
            if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) == 0:
                try:
                    return Path(path.value)
                finally:
                    ctypes.WinDLL("ole32").CoTaskMemFree(path)
        except (OSError, AttributeError, ValueError):
            pass
    return Path.home() / name


def downloads_root():
    downloads = known_folder("Downloads")
    return (downloads if downloads.is_dir() else Path.home()) / "apmyx"


def default_folders():
    root = downloads_root()
    return {key: str(root / name) for key, name in SUBFOLDERS.items()}


def normalized(value):
    return os.path.normcase(os.path.normpath(str(value)))


def previous_defaults(key):
    roots = {known_folder("Music") / "apmyx-downloads", Path.home() / "Music" / "apmyx-downloads", Path.home() / "apmyx-downloads"}
    return {normalized(RELATIVE_DEFAULTS[key])} | {normalized(root / SUBFOLDERS[key]) for root in roots}


def save_folder(settings, key):
    value = settings.get(key)
    if not value or normalized(value) in previous_defaults(key):
        value = default_folders()[key]
    return Path(value).resolve()


def upgrade_folders(config):
    defaults = default_folders()
    changed = {key: defaults[key] for key in SUBFOLDERS if config.get(key) and normalized(config[key]) in previous_defaults(key)}
    return {**config, **changed}, bool(changed)


def save_folders(settings):
    return [save_folder(settings, key) for key in SUBFOLDERS]


def blocked_folder_hint(message):
    if sys.platform != "win32" or not any(marker in message for marker in BLOCK_MARKERS):
        return ""
    text = message.replace("\\\\", "\\").replace("\\", "/").lower()
    for name in PROTECTED:
        for folder in {known_folder(name), Path.home() / name}:
            if str(folder).replace("\\", "/").lower().rstrip("/") + "/" in text:
                return (
                    f"Windows Controlled Folder Access may have blocked apmyx from saving to your {name} folder. "
                    "Allow apmyx in Windows Security > Virus & threat protection > Ransomware protection, "
                    "or choose another download folder in Settings."
                )
    return ""

import yaml

from backend.shared.folders import upgrade_folders

from .resources import app_dir


STOREFRONT_BACKUP = "storefront-before-applemusicdecrypt"


def sync_storefront(config):
    result = dict(config)
    selected = str(result.get("applemusicdecrypt-storefront") or "").strip().lower()
    active = (
        result.get("wrapper", "applemusicdecrypt") == "applemusicdecrypt"
        and len(selected) == 2 and selected.isascii() and selected.isalpha()
    )
    if active:
        if STOREFRONT_BACKUP not in result:
            result[STOREFRONT_BACKUP] = result.get("storefront", "")
        result["storefront"] = selected
    elif STOREFRONT_BACKUP in result:
        result["storefront"] = result.pop(STOREFRONT_BACKUP)
    return result


def config_path():
    return app_dir() / "config.yaml"


def upgrade_config(path=None):
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(config, dict):
        return
    config, changed = upgrade_folders(config)
    if changed:
        with open(path, "w", encoding="utf-8") as stream:
            yaml.dump(config, stream, sort_keys=False, allow_unicode=True)


def load_config(path=None):
    try:
        with open(path or config_path(), "r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream) or {}
    except FileNotFoundError:
        return {}
    if not isinstance(config, dict):
        raise ValueError("Configuration must contain a YAML mapping.")
    return sync_storefront(config)

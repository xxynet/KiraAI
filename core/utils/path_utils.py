from pathlib import Path


def get_root_path() -> Path:
    return Path().cwd().resolve()


def get_data_path() -> Path:
    return get_root_path() / "data"


def get_config_path() -> Path:
    return get_data_path() / "config"

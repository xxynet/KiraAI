import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

from webui import utils as webui_utils
from webui.routes import settings as settings_routes
from webui.routes.settings import SettingsRoutes


def make_data_dir(tmp_path: Path) -> Path:
    data_path = tmp_path / "data"
    (data_path / "config").mkdir(parents=True)
    (data_path / "webui.json").write_text(
        json.dumps({"host": "0.0.0.0", "port": 5267, "access_token": "live-token"}),
        encoding="utf-8",
    )
    (data_path / ".jwt_secret").write_text("live-secret", encoding="utf-8")
    return data_path


def make_archive(tmp_path: Path, include_credentials: bool = True) -> Path:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("config/kira.json", '{"restored": true}')
        if include_credentials:
            zf.writestr("webui.json", json.dumps({
                "host": "127.0.0.1",
                "port": 6000,
                "access_token": "token-from-archive",
            }))
            zf.writestr(".jwt_secret", "secret-from-archive")
    return archive


def make_routes(data_path: Path, monkeypatch) -> SettingsRoutes:
    monkeypatch.setattr(settings_routes, "get_data_path", lambda: data_path)
    monkeypatch.setattr(webui_utils, "get_data_path", lambda: data_path)
    return SettingsRoutes(FastAPI(), SimpleNamespace())


def test_restore_keeps_live_credentials(tmp_path: Path, monkeypatch) -> None:
    data_path = make_data_dir(tmp_path)
    routes = make_routes(data_path, monkeypatch)

    result = routes._do_restore(make_archive(tmp_path))

    assert result.success is True
    config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert config["access_token"] == "live-token"
    # Non-credential settings are still restored from the archive
    assert config["port"] == 6000
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "live-secret"
    assert (data_path / "config" / "kira.json").read_text(encoding="utf-8") == '{"restored": true}'


def test_restore_without_archived_credentials_leaves_them_alone(tmp_path: Path, monkeypatch) -> None:
    data_path = make_data_dir(tmp_path)
    routes = make_routes(data_path, monkeypatch)

    result = routes._do_restore(make_archive(tmp_path, include_credentials=False))

    assert result.success is True
    config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert config["access_token"] == "live-token"
    assert config["port"] == 5267
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "live-secret"


def test_restore_drops_archived_token_when_none_is_active(tmp_path: Path, monkeypatch) -> None:
    data_path = make_data_dir(tmp_path)
    (data_path / "webui.json").write_text(
        json.dumps({"host": "0.0.0.0", "port": 5267}), encoding="utf-8",
    )
    routes = make_routes(data_path, monkeypatch)

    routes._do_restore(make_archive(tmp_path))

    config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert "access_token" not in config

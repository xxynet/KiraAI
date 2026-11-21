import os
import stat

import pytest

from core.config.config_loader import KiraConfig


class MockConfig(KiraConfig):
    """KiraConfig that skips file I/O for unit testing."""
    def __init__(self, data: dict | None = None):
        object.__setattr__(self, "default_config", data or {})
        self.update(self.default_config)

    def _load_config(self):
        pass

    def save_config(self):
        pass


def test_deep_update_simple():
    c = MockConfig({"a": 1, "b": 2})
    c._deep_update(c, {"b": 99, "c": 3})
    assert c["a"] == 1
    assert c["b"] == 99
    assert c["c"] == 3


def test_deep_update_nested():
    c = MockConfig({"db": {"host": "localhost", "port": 5432}})
    c._deep_update(c, {"db": {"port": 3306}})
    assert c["db"]["host"] == "localhost"
    assert c["db"]["port"] == 3306


def test_deep_update_nested_new_key():
    c = MockConfig({"db": {"host": "localhost"}})
    c._deep_update(c, {"db": {"user": "admin"}})
    assert c["db"]["host"] == "localhost"
    assert c["db"]["user"] == "admin"


def test_deep_update_overwrite_dict_with_non_dict():
    c = MockConfig({"db": {"host": "localhost"}})
    c._deep_update(c, {"db": "disabled"})
    assert c["db"] == "disabled"


def test_get_config_simple():
    c = MockConfig({"key": "value"})
    assert c.get_config("key") == "value"


def test_get_config_nested():
    c = MockConfig({"a": {"b": {"c": 42}}})
    assert c.get_config("a.b.c") == 42


def test_get_config_missing_returns_default():
    c = MockConfig({})
    assert c.get_config("no.such.key", default="fallback") == "fallback"


def test_get_config_partial_path_returns_default():
    c = MockConfig({"a": {"b": 1}})
    assert c.get_config("a.b.c", default=None) is None


def test_get_config_custom_splitter():
    c = MockConfig({"a": {"b": "v"}})
    assert c.get_config("a/b", splitter="/") == "v"


def test_setattr_getattr():
    c = MockConfig({})
    c.foo = "bar"
    assert c.foo == "bar"
    assert c["foo"] == "bar"


def test_getattr_missing_raises():
    c = MockConfig({})
    with pytest.raises(AttributeError, match="no attribute"):
        _ = c.nonexistent


def test_delattr():
    c = MockConfig({"key": "val"})
    del c.key
    assert "key" not in c


def test_delattr_missing_raises():
    c = MockConfig({})
    with pytest.raises(AttributeError, match="no attribute"):
        del c.nonexistent


def test_default_config_merged():
    c = MockConfig({"a": 1, "b": {"x": 10}})
    assert c["a"] == 1
    assert c["b"]["x"] == 10


@pytest.mark.anyio
@pytest.mark.parametrize(("field", "default", "value"), [
    ("session_retention_hours", 0, 7),
    ("max_concurrent_per_session", 4, 2),
])
async def test_subagent_settings_are_validated_and_saved(monkeypatch, tmp_path, field, default, value):
    from types import SimpleNamespace

    from fastapi import FastAPI, HTTPException

    from core.config import config_loader
    from webui.routes.config import ConfigRoutes

    monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "config.json")
    config = KiraConfig()
    routes = ConfigRoutes(FastAPI(), SimpleNamespace(kira_config=config))
    assert config["bot_config"]["subagent"][field] == default

    invalid_sections = [None, {field: -1}, {field: True}, {field: 1.5}, {field: "7"}]
    if field == "max_concurrent_per_session":
        invalid_sections.append({field: 0})
    for invalid in invalid_sections:
        with pytest.raises(HTTPException) as exc:
            await routes.update_configuration({"bot_config": {**config["bot_config"], "subagent": invalid}})
        assert exc.value.status_code == 400
        assert config["bot_config"]["subagent"][field] == default

    payload = {**config["bot_config"], "subagent": {**config["bot_config"]["subagent"], field: value}}
    await routes.update_configuration({"bot_config": payload})
    assert KiraConfig()["bot_config"]["subagent"][field] == value


def test_save_config_opt_in_errors_preserve_existing_caller_behavior(monkeypatch, tmp_path):
    from core.config import ConfigError, config_loader

    monkeypatch.setattr(config_loader, 'CONFIG_PATH', tmp_path / 'config.json')
    config = KiraConfig({'test': True})
    assert config.save_config(raise_on_error=True) is None

    before = config_loader.CONFIG_PATH.read_text(encoding='utf-8')

    def fail_replace(*args, **kwargs):
        raise OSError('Simulated write failure')

    monkeypatch.setattr(config_loader.os, 'replace', fail_replace)
    assert config.save_config() is None
    assert config_loader.CONFIG_PATH.read_text(encoding='utf-8') == before
    with pytest.raises(ConfigError, match='failed to save configuration') as error:
        config.save_config(raise_on_error=True)
    assert isinstance(error.value.__cause__, OSError)
    assert config_loader.CONFIG_PATH.read_text(encoding='utf-8') == before


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are unavailable on Windows")
def test_atomic_save_preserves_existing_file_mode(monkeypatch, tmp_path):
    from core.config import config_loader

    path = tmp_path / "config.json"
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"value": 1})
    path.chmod(0o640)
    config["value"] = 2
    config.save_config(raise_on_error=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_atomic_save_preserves_symlink_and_updates_target(monkeypatch, tmp_path):
    import json

    from core.config import config_loader

    target = tmp_path / "mounted_config" / "config.json"
    target.parent.mkdir()
    target.write_text('{"value": 1}', encoding="utf-8")
    path = tmp_path / "config.json"
    try:
        path.symlink_to(target)
    except OSError as exc:
        if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 1314:
            pytest.skip(f"Symbolic link creation requires privileges: {exc}")
        raise
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"value": 1})
    config["value"] = 2
    config.save_config(raise_on_error=True)
    assert path.is_symlink()
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 2}


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only file cleanup")
@pytest.mark.parametrize("raise_on_error", [False, True])
def test_atomic_save_cleans_readonly_temporary_file(monkeypatch, tmp_path, raise_on_error):
    from core.config import ConfigError, config_loader

    path = tmp_path / "config.json"
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"value": 1})
    before = path.read_bytes()
    path.chmod(stat.S_IREAD)
    config["value"] = 2
    try:
        if raise_on_error:
            with pytest.raises(ConfigError) as error:
                config.save_config(raise_on_error=True)
            assert isinstance(error.value.__cause__, PermissionError)
        else:
            assert config.save_config() is None
        assert path.read_bytes() == before
        assert not path.stat().st_mode & stat.S_IWRITE
        assert not list(tmp_path.glob(".system_config.*.tmp"))
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        for temporary in tmp_path.glob(".system_config.*.tmp"):
            temporary.chmod(stat.S_IREAD | stat.S_IWRITE)
            temporary.unlink()


def test_atomic_save_serialization_failure_preserves_original(monkeypatch, tmp_path):
    from core.config import ConfigError, config_loader

    path = tmp_path / "config.json"
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"value": 1})
    before = path.read_bytes()
    config["invalid"] = object()
    with pytest.raises(ConfigError) as error:
        config.save_config(raise_on_error=True)
    assert isinstance(error.value.__cause__, TypeError)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".system_config.*.tmp"))


def test_atomic_save_logs_cleanup_failure_without_masking_save_error(monkeypatch, tmp_path):
    from core.config import ConfigError, config_loader

    monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "config.json")
    config = KiraConfig({"value": 1})
    messages = []
    monkeypatch.setattr(config_loader.logger, "error", messages.append)

    def fail_replace(*args, **kwargs):
        raise PermissionError("Simulated replacement failure")

    def fail_unlink(*args, **kwargs):
        raise OSError("Simulated temporary file cleanup failure")

    monkeypatch.setattr(config_loader.os, "replace", fail_replace)
    monkeypatch.setattr(config_loader.os, "unlink", fail_unlink)
    with pytest.raises(ConfigError) as error:
        config.save_config(raise_on_error=True)
    assert isinstance(error.value.__cause__, PermissionError)
    assert str(error.value.__cause__) == "Simulated replacement failure"
    temporary, = tmp_path.glob(".system_config.*.tmp")
    assert any(str(temporary) in message and "Simulated temporary file cleanup failure" in message
               for message in messages)

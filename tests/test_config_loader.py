import pytest

from core.config.config_loader import KiraConfig


class MockConfig(KiraConfig):
    """KiraConfig that skips file I/O for unit testing."""
    def __init__(self, data: dict = None):
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

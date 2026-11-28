import json

import pytest

from webui import utils
from webui.utils import _tokens_match


def test_tokens_match_compares_exactly():
    assert _tokens_match("token", "token")
    assert not _tokens_match("token", "Token")
    assert not _tokens_match("token", "token ")
    assert not _tokens_match(None, "token")
    assert not _tokens_match("token", None)
    assert _tokens_match("秘密令牌", "秘密令牌")


@pytest.fixture
def config_path(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "get_data_path", lambda: tmp_path)
    return tmp_path / "webui.json"


@pytest.mark.parametrize("invalid", ["", None, 123, " \t", " token", "token ", "\ufefftoken", "disabled"])
def test_unusable_token_is_replaced_once(config_path, invalid):
    config_path.write_text(json.dumps({"access_token": invalid, "port": 5300}))

    token, generated = utils._get_or_generate_access_token()

    assert generated
    assert utils._is_usable_access_token(token)
    assert json.loads(config_path.read_text()) == {"access_token": token, "port": 5300}
    assert utils._get_or_generate_access_token() == (token, False)


def test_absent_config_is_created(config_path):
    token, generated = utils._get_or_generate_access_token()

    assert generated
    assert json.loads(config_path.read_text())["access_token"] == token


@pytest.mark.parametrize("raw", [b"", b"{bad json", b"[]", b"null", b"\xff"])
def test_damaged_config_is_preserved(config_path, raw):
    config_path.write_bytes(raw)

    assert utils._get_or_generate_access_token() == (None, False)
    assert config_path.read_bytes() == raw


def test_existing_token_is_reused_without_writing(config_path):
    raw = '{"access_token": "existing-token", "port": 5300}'
    config_path.write_text(raw)

    assert utils._get_or_generate_access_token() == ("existing-token", False)
    assert config_path.read_text() == raw


def test_failed_write_preserves_config(config_path, monkeypatch):
    raw = '{"access_token": ""}'
    config_path.write_text(raw)

    def fail_replace(*args):
        raise PermissionError("read-only config")

    monkeypatch.setattr(utils.os, "replace", fail_replace)

    assert utils._get_or_generate_access_token() == (None, False)
    assert config_path.read_text() == raw
    assert list(config_path.parent.iterdir()) == [config_path]


def test_write_must_be_verified(monkeypatch, config_path):
    config_path.write_text('{"access_token": ""}')
    monkeypatch.setattr(utils, "_save_webui_config", lambda config: None)

    assert utils._get_or_generate_access_token() == (None, False)

import importlib
import json
from pathlib import Path

import pytest

from core.chat.message_elements import File, Image

kira_tags = importlib.import_module("core.plugin.builtin_plugins.kira-ai.tags")
file_send_policy = importlib.import_module(
    "core.plugin.builtin_plugins.kira-ai.file_send_policy"
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolate the data root and the agent plugin config file per test."""
    data_root = tmp_path / "data"
    config_root = tmp_path / "config"
    for sub in ("files", "temp"):
        (data_root / sub).mkdir(parents=True)
    (config_root / "plugins").mkdir(parents=True)
    monkeypatch.setattr(file_send_policy, "get_data_path", lambda: data_root)
    monkeypatch.setattr(file_send_policy, "get_config_path", lambda: config_root)
    return data_root, config_root


def write_agent_config(config_root: Path, file_access: dict):
    config_path = config_root / "plugins" / "agent.json"
    config_path.write_text(
        json.dumps({"file_access": file_access}, ensure_ascii=False),
        encoding="utf-8",
    )


def build_tag(sid: str = ""):
    return kira_tags.build_file_tag(sid=sid)()


@pytest.mark.anyio
async def test_data_temp_relative_send_allowed(sandbox):
    data_root, _ = sandbox
    target = data_root / "temp" / "report.txt"
    target.write_text("hello", encoding="utf-8")

    result = await build_tag().handle("data/temp/report.txt")

    assert len(result) == 1
    assert isinstance(result[0], File)
    assert Path(result[0].file) == target


@pytest.mark.anyio
async def test_absolute_under_data_files_allowed(sandbox):
    data_root, _ = sandbox
    target = data_root / "files" / "a.txt"
    target.write_text("content", encoding="utf-8")

    result = await build_tag().handle(str(target))

    assert len(result) == 1
    assert isinstance(result[0], File)


@pytest.mark.anyio
async def test_path_traversal_rejected(sandbox):
    data_root, _ = sandbox
    secret = tmp_secret = data_root.parent / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    assert await build_tag().handle("data/../secret.txt") == []
    assert await build_tag().handle("../secret.txt") == []


@pytest.mark.anyio
async def test_restricted_keyword_rejected(sandbox):
    data_root, _ = sandbox
    target = data_root / "files" / "token.txt"
    target.write_text("content", encoding="utf-8")

    assert await build_tag().handle("data/files/token.txt") == []


@pytest.mark.anyio
async def test_extra_path_allowed_for_whitelisted_session(sandbox):
    data_root, config_root = sandbox
    extra_dir = data_root.parent / "extra"
    extra_dir.mkdir()
    target = extra_dir / "doc.txt"
    target.write_text("doc", encoding="utf-8")
    write_agent_config(config_root, {
        "permission_mode": "allow_list",
        "session_list": ["test:dm:1"],
        "extra_read_paths": [str(extra_dir)],
    })

    result = await build_tag(sid="test:dm:1").handle(str(target))

    assert len(result) == 1
    assert isinstance(result[0], File)


@pytest.mark.anyio
async def test_extra_path_denied_for_other_session(sandbox):
    data_root, config_root = sandbox
    extra_dir = data_root.parent / "extra"
    extra_dir.mkdir()
    target = extra_dir / "doc.txt"
    target.write_text("doc", encoding="utf-8")
    write_agent_config(config_root, {
        "permission_mode": "allow_list",
        "session_list": ["test:dm:1"],
        "extra_read_paths": [str(extra_dir)],
    })

    assert await build_tag(sid="test:dm:2").handle(str(target)) == []
    # An unknown session context never qualifies for extra paths.
    assert await build_tag().handle(str(target)) == []


@pytest.mark.anyio
async def test_deny_list_mode_gates_extra_paths(sandbox):
    data_root, config_root = sandbox
    extra_dir = data_root.parent / "extra"
    extra_dir.mkdir()
    target = extra_dir / "doc.txt"
    target.write_text("doc", encoding="utf-8")
    write_agent_config(config_root, {
        "permission_mode": "deny_list",
        "session_list": ["test:dm:2"],
        "extra_read_paths": [str(extra_dir)],
    })

    # Sessions outside the deny list may use extra paths...
    assert len(await build_tag(sid="test:dm:1").handle(str(target))) == 1
    # ...while listed ones may not.
    assert await build_tag(sid="test:dm:2").handle(str(target)) == []


@pytest.mark.anyio
async def test_missing_agent_config_keeps_base_paths(sandbox):
    data_root, config_root = sandbox
    target = data_root / "files" / "a.txt"
    target.write_text("content", encoding="utf-8")

    assert len(await build_tag(sid="test:dm:1").handle("data/files/a.txt")) == 1

    outside = data_root.parent / "doc.txt"
    outside.write_text("doc", encoding="utf-8")
    assert await build_tag(sid="test:dm:1").handle(str(outside)) == []


@pytest.mark.anyio
async def test_url_bypasses_path_checks(sandbox):
    result = await build_tag().handle("https://example.com/audio.mp3")

    assert len(result) == 1
    assert isinstance(result[0], File)
    assert result[0].file == "https://example.com/audio.mp3"
    assert result[0].name is None


@pytest.mark.anyio
async def test_type_image_returns_image_element(sandbox):
    data_root, _ = sandbox
    target = data_root / "files" / "pic.png"
    target.write_bytes(b"\x89PNG")

    result = await build_tag().handle("data/files/pic.png", type="image")

    assert len(result) == 1
    assert isinstance(result[0], Image)


@pytest.mark.anyio
async def test_bare_relative_path_rejected(sandbox):
    data_root, _ = sandbox
    target = data_root / "report.txt"
    target.write_text("content", encoding="utf-8")

    assert await build_tag().handle("report.txt") == []


@pytest.mark.anyio
async def test_missing_file_returns_empty(sandbox):
    assert await build_tag().handle("data/temp/ghost.txt") == []

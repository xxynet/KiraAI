"""Tests for the agent plugin migrating config written in older layouts.

The plugin used to be ``file`` and its settings were flat top-level keys. They now
live in sections (``tools``, ``file_access``, ``exec_access``) and the session
permissions gained allow_list / deny_list modes. ``AgentPlugin`` folds every older
layout into the current one on its own, without any registry-side support, and
deletes the legacy ``file.json`` after a successful migration, which is what makes
the migration run exactly once.
"""

import copy
import json

import pytest

from core.plugin.builtin_plugins.agent import main as agent_main
from core.plugin.builtin_plugins.agent.main import AgentPlugin


# Config as the old "file" plugin wrote it: flat keys, no sections, no modes
LEGACY_CONFIG = {
    "allowed_sessions": ["dc:dm:42"],
    "allowed_exec_sessions": ["tg:dm:7"],
    "enabled_tools": ["exec"],
    "exec_deny_list": ["shutdown"],
    "exec_timeout": 5,
    "background_exec_timeout": 120,
    "background_exec_wait_seconds": 4,
    "extra_paths": {
        "extra_read_paths": ["E:/Oriha_MCP"],
        "extra_write_paths": ["E:/Oriha_MCP"],
    },
}

# What the registry hands over before any migration: schema defaults only
SCHEMA_DEFAULTS = {
    "tools": {"enabled_tools": ["read_file", "write_file", "exec"]},
    "file_access": {
        "permission_mode": "allow_list",
        "session_list": [],
        "extra_read_paths": [],
        "extra_write_paths": [],
    },
    "exec_access": {
        "permission_mode": "allow_list",
        "session_list": [],
        "command_deny_list": ["shutdown", "poweroff", "sudo"],
        "timeout": 30,
        "background_timeout": 300,
        "background_wait_seconds": 2,
    },
}


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point the plugin at a throwaway data directory."""
    config_dir = tmp_path / "data" / "config" / "plugins"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(agent_main, "get_config_path", lambda: tmp_path / "data" / "config")
    return config_dir


def _write_legacy(config_dir, payload) -> None:
    path = config_dir / "file.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _read_config(config_dir, plugin_id: str = "agent") -> dict:
    return json.loads((config_dir / f"{plugin_id}.json").read_text(encoding="utf-8"))


def _plugin(cfg: dict | None = None) -> AgentPlugin:
    return AgentPlugin(None, copy.deepcopy(cfg if cfg is not None else SCHEMA_DEFAULTS))


def test_legacy_settings_land_in_their_section(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()

    assert plugin._migrate_legacy_config() is True

    cfg = plugin.plugin_cfg
    assert cfg["tools"]["enabled_tools"] == ["exec"]
    assert cfg["file_access"]["session_list"] == ["dc:dm:42"]
    assert cfg["file_access"]["extra_read_paths"] == ["E:/Oriha_MCP"]
    assert cfg["file_access"]["extra_write_paths"] == ["E:/Oriha_MCP"]
    assert cfg["exec_access"]["session_list"] == ["tg:dm:7"]
    assert cfg["exec_access"]["command_deny_list"] == ["shutdown"]
    assert cfg["exec_access"]["timeout"] == 5
    assert cfg["exec_access"]["background_timeout"] == 120
    assert cfg["exec_access"]["background_wait_seconds"] == 4
    # Flat keys are gone, so the reshape cannot run twice
    assert "allowed_sessions" not in cfg
    assert "allowed_exec_sessions" not in cfg
    assert "exec_deny_list" not in cfg
    assert "extra_paths" not in cfg


def test_legacy_permissions_keep_their_allow_list_meaning(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()

    plugin._migrate_legacy_config()

    # The old lists were allow lists, and an absent mode must not turn them around
    assert plugin.plugin_cfg["file_access"]["permission_mode"] == "allow_list"
    assert plugin.plugin_cfg["exec_access"]["permission_mode"] == "allow_list"


def test_migration_removes_the_legacy_file(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)

    _plugin()._migrate_legacy_config()

    assert not (config_dir / "file.json").exists()
    assert _read_config(config_dir)["file_access"]["session_list"] == ["dc:dm:42"]


def test_second_run_is_a_noop_and_later_edits_win(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()
    plugin._migrate_legacy_config()

    # A WebUI edit after the migration
    plugin.plugin_cfg["file_access"]["session_list"] = ["dc:dm:99"]
    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg["file_access"]["session_list"] == ["dc:dm:99"]


def test_missing_legacy_file_is_a_noop(config_dir):
    plugin = _plugin()

    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg == SCHEMA_DEFAULTS
    assert not (config_dir / "agent.json").exists()


def test_corrupted_legacy_file_is_ignored_and_kept(config_dir):
    _write_legacy(config_dir, "{not valid json")
    plugin = _plugin()

    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg == SCHEMA_DEFAULTS
    assert (config_dir / "file.json").exists()


def test_non_object_legacy_file_is_ignored_and_kept(config_dir):
    _write_legacy(config_dir, json.dumps(["not", "an", "object"]))
    plugin = _plugin()

    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg == SCHEMA_DEFAULTS
    assert (config_dir / "file.json").exists()


def test_legacy_file_is_kept_when_persisting_fails(config_dir, monkeypatch):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()
    monkeypatch.setattr(plugin, "_persist_config", lambda: False)

    assert plugin._migrate_legacy_config() is False

    # Nothing is lost: the legacy file survives so a later startup can retry
    assert (config_dir / "file.json").exists()
    assert not (config_dir / "agent.json").exists()


def test_flat_config_of_the_rename_build_is_reshaped(config_dir):
    """The rename build could already have copied flat keys into agent.json."""
    plugin = _plugin({
        **SCHEMA_DEFAULTS,
        "allowed_sessions": ["dc:dm:42"],
        "exec_timeout": 5,
        "extra_paths": {"extra_read_paths": ["E:/Oriha_MCP"]},
    })

    assert plugin._migrate_legacy_config() is True

    assert plugin.plugin_cfg["file_access"]["session_list"] == ["dc:dm:42"]
    assert plugin.plugin_cfg["file_access"]["extra_read_paths"] == ["E:/Oriha_MCP"]
    assert plugin.plugin_cfg["exec_access"]["timeout"] == 5
    assert "allowed_sessions" not in plugin.plugin_cfg
    assert not (config_dir / "file.json").exists()
    assert _read_config(config_dir)["file_access"]["session_list"] == ["dc:dm:42"]


def test_reshape_runs_once_and_keeps_unrelated_keys(config_dir):
    plugin = _plugin({
        **SCHEMA_DEFAULTS,
        "allowed_sessions": ["dc:dm:42"],
        "some_future_key": 1,
    })
    plugin._migrate_legacy_config()

    persisted = _read_config(config_dir)
    assert persisted["some_future_key"] == 1

    assert _plugin(persisted)._migrate_legacy_config() is False


def test_malformed_extra_paths_is_left_alone(config_dir):
    plugin = _plugin({**SCHEMA_DEFAULTS, "extra_paths": "nonsense"})

    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg["extra_paths"] == "nonsense"


@pytest.mark.anyio
async def test_initialize_persists_migration_and_applies_it(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()

    await plugin.initialize()

    persisted = _read_config(config_dir)
    assert persisted["file_access"]["session_list"] == ["dc:dm:42"]
    assert persisted["exec_access"]["timeout"] == 5
    # The migrated values are in effect for this run, not just on disk
    assert plugin.file_sessions == ["dc:dm:42"]
    assert plugin.exec_sessions == ["tg:dm:7"]
    assert plugin.file_permission_mode == "allow_list"
    assert plugin.exec_permission_mode == "allow_list"
    assert plugin._exec_timeout == 5
    assert "E:/Oriha_MCP" in plugin.allowed_read_paths
    assert "E:/Oriha_MCP" in plugin.allowed_write_paths


@pytest.mark.anyio
async def test_initialize_without_legacy_file_writes_nothing(config_dir):
    plugin = _plugin()

    await plugin.initialize()

    assert not (config_dir / "agent.json").exists()
    assert plugin.file_sessions == []


@pytest.mark.anyio
async def test_initialize_does_not_rewrite_after_migration(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    await _plugin().initialize()
    migrated_on_disk = _read_config(config_dir)

    # Second startup: the legacy file is gone, so nothing is migrated or rewritten
    plugin = _plugin(migrated_on_disk)
    plugin.plugin_cfg["file_access"]["session_list"] = ["dc:dm:99"]
    await plugin.initialize()

    assert plugin.file_sessions == ["dc:dm:99"]
    assert _read_config(config_dir) == migrated_on_disk

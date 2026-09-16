"""Tests for the agent plugin migrating the config of its pre-rename identity.

The plugin used to be ``file``; ``AgentPlugin`` inherits the settings users
already made in ``file.json`` on its own, without any registry-side support.
The legacy file is deleted after a successful migration, which is what makes the
migration run exactly once.
"""

import json

import pytest

from core.plugin.builtin_plugins.agent import main as agent_main
from core.plugin.builtin_plugins.agent.main import AgentPlugin


LEGACY_CONFIG = {
    "allowed_sessions": ["dc:dm:42"],
    "allowed_exec_sessions": ["tg:dm:7"],
    "enabled_tools": ["exec"],
    "exec_timeout": 5,
    "extra_paths": {
        "extra_read_paths": ["E:/Oriha_MCP"],
        "extra_write_paths": ["E:/Oriha_MCP"],
    },
}

# What the registry hands over before any migration: schema defaults only
SCHEMA_DEFAULTS = {
    "enabled_tools": ["read_file", "write_file", "exec"],
    "allowed_sessions": [],
    "allowed_exec_sessions": [],
    "exec_timeout": 30,
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
    return AgentPlugin(None, dict(cfg if cfg is not None else SCHEMA_DEFAULTS))


def test_legacy_settings_override_schema_defaults(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()

    assert plugin._migrate_legacy_config() is True

    assert plugin.plugin_cfg["allowed_sessions"] == ["dc:dm:42"]
    assert plugin.plugin_cfg["enabled_tools"] == ["exec"]
    assert plugin.plugin_cfg["exec_timeout"] == 5
    assert plugin.plugin_cfg["extra_paths"]["extra_read_paths"] == ["E:/Oriha_MCP"]


def test_migration_removes_the_legacy_file(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)

    _plugin()._migrate_legacy_config()

    assert not (config_dir / "file.json").exists()
    assert _read_config(config_dir)["allowed_sessions"] == ["dc:dm:42"]


def test_second_run_is_a_noop_and_later_edits_win(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()
    plugin._migrate_legacy_config()

    # A WebUI edit after the migration
    plugin.plugin_cfg["allowed_sessions"] = ["dc:dm:99"]
    assert plugin._migrate_legacy_config() is False

    assert plugin.plugin_cfg["allowed_sessions"] == ["dc:dm:99"]


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


@pytest.mark.anyio
async def test_initialize_persists_migration_and_applies_it(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    plugin = _plugin()

    await plugin.initialize()

    persisted = _read_config(config_dir)
    assert persisted["allowed_sessions"] == ["dc:dm:42"]
    assert persisted["exec_timeout"] == 5
    # The migrated values are in effect for this run, not just on disk
    assert plugin.allowed_sessions == ["dc:dm:42"]
    assert plugin.allowed_exec_sessions == ["tg:dm:7"]
    assert plugin._exec_timeout == 5
    assert "E:/Oriha_MCP" in plugin.allowed_read_paths
    assert "E:/Oriha_MCP" in plugin.allowed_write_paths


@pytest.mark.anyio
async def test_initialize_without_legacy_file_writes_nothing(config_dir):
    plugin = _plugin()

    await plugin.initialize()

    assert not (config_dir / "agent.json").exists()
    assert plugin.allowed_sessions == []


@pytest.mark.anyio
async def test_initialize_does_not_rewrite_after_migration(config_dir):
    _write_legacy(config_dir, LEGACY_CONFIG)
    await _plugin().initialize()
    migrated_on_disk = _read_config(config_dir)

    # Second startup: the legacy file is gone, so nothing is migrated or rewritten
    plugin = _plugin(dict(migrated_on_disk))
    plugin.plugin_cfg["allowed_sessions"] = ["dc:dm:99"]
    await plugin.initialize()

    assert plugin.allowed_sessions == ["dc:dm:99"]
    assert _read_config(config_dir) == migrated_on_disk
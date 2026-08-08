import asyncio
import io
import json
import zipfile

import pytest

import core.plugin.plugin_installer as plugin_installer


def _plugin_archive(plugin_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin-main/manifest.json", json.dumps({"plugin_id": plugin_id}))
        archive.writestr("plugin-main/main.py", "# plugin entry point\n")
    return buffer.getvalue()


def test_install_rejects_registered_plugin_before_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    with pytest.raises(plugin_installer.PluginAlreadyInstalledError):
        asyncio.run(
            plugin_installer.install_from_zip(
                _plugin_archive("existing-plugin"),
                tmp_path / "plugins",
                is_plugin_installed=lambda plugin_id: plugin_id == "existing-plugin",
            )
        )

    assert not (tmp_path / "plugins" / "existing-plugin").exists()
    assert not list((tmp_path / "temp").glob("extract_*"))


def test_update_replaces_legacy_plugin_directory(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    legacy_dir = plugins_dir / "repository-folder"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "stale.txt").write_text("old plugin", encoding="utf-8")
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    installed_dir = asyncio.run(
        plugin_installer.install_from_zip(
            _plugin_archive("plugin-id"),
            plugins_dir,
            target_dir=legacy_dir,
        )
    )

    assert installed_dir == legacy_dir
    assert not (legacy_dir / "stale.txt").exists()
    assert not (plugins_dir / "plugin-id").exists()

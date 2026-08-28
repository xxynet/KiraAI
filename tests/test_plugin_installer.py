import asyncio
import io
import json
import zipfile
from pathlib import Path

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


def test_update_rejects_a_changed_plugin_id_before_replacing_files(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    legacy_dir = plugins_dir / "repository-folder"
    legacy_dir.mkdir(parents=True)
    stale_file = legacy_dir / "stale.txt"
    stale_file.write_text("old plugin", encoding="utf-8")
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    with pytest.raises(ValueError, match="Plugin identity changed"):
        asyncio.run(
            plugin_installer.install_from_zip(
                _plugin_archive("different-plugin-id"),
                plugins_dir,
                target_dir=legacy_dir,
                expected_plugin_id="plugin-id",
            )
        )

    assert stale_file.read_text(encoding="utf-8") == "old plugin"
    assert not (legacy_dir / "main.py").exists()


def test_install_from_github_downloads_the_requested_commit(tmp_path, monkeypatch):
    downloaded_urls = []

    async def fake_download(url, target, proxy=None):
        downloaded_urls.append(url)
        Path(target).write_bytes(_plugin_archive("plugin-id"))

    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "download_file", fake_download)
    commit_sha = "a" * 40

    asyncio.run(
        plugin_installer.install_from_github(
            "https://github.com/example/plugin",
            tmp_path / "plugins",
            commit_sha=commit_sha,
        )
    )

    assert downloaded_urls == [
        f"https://github.com/example/plugin/archive/{commit_sha}.zip"
    ]

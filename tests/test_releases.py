import zipfile
from pathlib import Path

from webui.routes import releases


def test_apply_update_removes_stale_backup_paths(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "config.json").write_text("old config", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "old.txt").write_text("old asset", encoding="utf-8")

    stale_file_backup = root / "config.json.bak"
    stale_file_backup.mkdir()
    (stale_file_backup / "stale.txt").write_text("stale", encoding="utf-8")
    stale_dir_backup = root / "assets.bak"
    stale_dir_backup.write_text("stale", encoding="utf-8")

    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("KiraAI-release/config.json", "new config")
        zf.writestr("KiraAI-release/assets/new.txt", "new asset")

    monkeypatch.setattr(releases, "get_root_path", lambda: root)

    releases.ReleasesRoutes._apply_update(archive)

    assert (root / "config.json").read_text(encoding="utf-8") == "new config"
    assert (root / "assets" / "new.txt").read_text(encoding="utf-8") == "new asset"
    assert not stale_file_backup.exists()
    assert not stale_dir_backup.exists()

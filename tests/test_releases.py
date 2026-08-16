import io
import tempfile
import zipfile
from pathlib import Path

from core.utils import dist_checker
from core.utils.update_transaction import JOURNAL_NAME, STAGE_PREFIX, UpdateTransaction, recover_interrupted_update
from webui.routes import releases


def test_apply_update_replaces_files_and_leaves_legacy_backups_untouched(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / "config.json").write_text("old config", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "old.txt").write_text("old asset", encoding="utf-8")

    stale_dir_artifact = root / "config.json.bak"
    stale_dir_artifact.mkdir()
    (stale_dir_artifact / "stale.txt").write_text("stale", encoding="utf-8")
    stale_file_artifact = root / "assets.bak"
    stale_file_artifact.write_text("stale", encoding="utf-8")

    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("KiraAI-release/config.json", "new config")
        zf.writestr("KiraAI-release/assets/new.txt", "new asset")

    monkeypatch.setattr(releases, "get_root_path", lambda: root)

    releases.ReleasesRoutes._apply_update(archive)

    assert (root / "config.json").read_text(encoding="utf-8") == "new config"
    assert (root / "assets" / "new.txt").read_text(encoding="utf-8") == "new asset"
    assert stale_dir_artifact.exists()
    assert stale_file_artifact.exists()


def test_apply_update_stages_on_application_filesystem(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "app"
    root.mkdir()
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("KiraAI-release/main.py", "print('updated')")

    created_stage_dirs: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def record_mkdtemp(*args, **kwargs):
        path = Path(real_mkdtemp(*args, **kwargs))
        if kwargs.get("prefix") == STAGE_PREFIX:
            created_stage_dirs.append(path)
        return str(path)

    monkeypatch.setattr(releases.tempfile, "mkdtemp", record_mkdtemp)
    monkeypatch.setattr(releases, "get_root_path", lambda: root)

    releases.ReleasesRoutes._apply_update(archive)

    assert created_stage_dirs
    assert all(stage.parent == root for stage in created_stage_dirs)


def test_recovery_replaces_new_destination_with_backup_after_interrupted_update(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("before", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    (stage / "AGENTS.md").write_text("after", encoding="utf-8")

    transaction = UpdateTransaction(root, stage, ["AGENTS.md"])
    transaction.apply()
    transaction.data["actions"][0]["state"] = "original_moved"
    transaction._save()

    assert target.read_text(encoding="utf-8") == "after"
    assert (root / JOURNAL_NAME).exists()

    assert recover_interrupted_update(root) == []
    assert target.read_text(encoding="utf-8") == "before"
    assert not (root / JOURNAL_NAME).exists()


def test_committed_transaction_keeps_new_file_and_removes_backup(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("before", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    (stage / "AGENTS.md").write_text("after", encoding="utf-8")

    transaction = UpdateTransaction(root, stage, ["AGENTS.md"])
    transaction.apply()
    transaction.data["phase"] = "committed"
    transaction._save()

    assert recover_interrupted_update(root) == []
    assert target.read_text(encoding="utf-8") == "after"
    assert not (root / JOURNAL_NAME).exists()


def test_prepared_webui_archive_can_be_rolled_back(tmp_path: Path, monkeypatch) -> None:
    dist_dir = tmp_path / "data" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("before", encoding="utf-8")
    (dist_dir / ".version").write_text("v1.0.0", encoding="utf-8")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("dist/index.html", "after")
        zf.writestr("dist/assets/app.js", "console.log('updated')")

    monkeypatch.setattr(dist_checker, "get_dist_dir", lambda: dist_dir)
    transaction = dist_checker.apply_dist_archive(archive.getvalue(), "v2.0.0", keep_backup=True)

    assert transaction is not None
    assert (dist_dir / "index.html").read_text(encoding="utf-8") == "after"
    assert (dist_dir / ".version").read_text(encoding="utf-8") == "v2.0.0"
    assert transaction.rollback() == []
    assert (dist_dir / "index.html").read_text(encoding="utf-8") == "before"
    assert (dist_dir / ".version").read_text(encoding="utf-8") == "v1.0.0"

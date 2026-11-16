import tempfile
from pathlib import Path

from core.utils.update_transaction import (
    JOURNAL_NAME,
    STAGE_PREFIX,
    UpdateTransaction,
    recover_interrupted_update,
)


def test_recovery_does_not_delete_restored_original_when_backup_is_gone(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    target = root / "AGENTS.md"
    target.write_text("before", encoding="utf-8")
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    (stage / "AGENTS.md").write_text("after", encoding="utf-8")

    transaction = UpdateTransaction(root, stage, ["AGENTS.md"])
    transaction.apply()

    # Simulate a rollback that restored the original and was then interrupted
    # before the journal state was updated: backup is gone, dst is "before".
    target.write_text("before", encoding="utf-8")
    (transaction.backup_dir / "AGENTS.md").unlink()
    transaction.data["actions"][0]["state"] = "applied"
    transaction._save()

    assert recover_interrupted_update(root) == []
    assert target.read_text(encoding="utf-8") == "before"
    assert not (root / JOURNAL_NAME).exists()

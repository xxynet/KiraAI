import pytest

from core.agent.tool import ToolResult


class FakeAttachment:
    """Minimal attachment whose ``to_path`` yields a fixed path."""

    def __init__(self, path):
        self._path = path

    async def to_path(self):
        return self._path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    (data_root / "temp").mkdir(parents=True)
    monkeypatch.setattr("core.agent.tool.get_data_path", lambda: data_root)
    return data_root


@pytest.mark.anyio
async def test_outside_data_root_attachment_is_staged(sandbox):
    data_root = sandbox
    source = data_root.parent / "export" / "report.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("pdf-bytes", encoding="utf-8")

    result = ToolResult(attachments=[FakeAttachment(str(source))])
    text = await result.assemble_result()

    assert "data/temp/" in text
    # The advertised staged copy exists and carries the original content.
    advertised = text.split("data/temp/", 1)[1].splitlines()[0].strip()
    staged = data_root / "temp" / advertised
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == "pdf-bytes"
    # The original foreign path is no longer advertised.
    assert str(source) not in text


@pytest.mark.anyio
async def test_missing_outside_attachment_is_skipped(sandbox):
    ghost = sandbox.parent / "ghost.pdf"

    result = ToolResult(attachments=[FakeAttachment(str(ghost))])
    text = await result.assemble_result()

    assert "data/temp/" not in text
    assert "Attachments" not in text


@pytest.mark.anyio
async def test_data_root_attachment_keeps_relative_path(sandbox):
    data_root = sandbox
    source = data_root / "files" / "out.txt"
    source.parent.mkdir(parents=True)
    source.write_text("inside", encoding="utf-8")

    result = ToolResult(attachments=[FakeAttachment(str(source))])
    text = await result.assemble_result()

    assert "data/files/out.txt" in text

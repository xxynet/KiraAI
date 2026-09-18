import os
import base64
import tempfile

import pytest

from core.chat.message_elements import (
    _infer_mime_from_bytes,
    check_base64,
    ElementType,
    Text,
    At,
    Reply,
    Emoji,
    Notice,
    Poke,
    Json,
    Image,
    Sticker,
    Record,
    File,
    Video,
    BaseMediaElement,
)


# ── _infer_mime_from_bytes ──────────────────────────────────────────

def test_infer_png():
    data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8
    assert _infer_mime_from_bytes(data) == "image/png"


def test_infer_gif():
    data = b'GIF89a' + b'\x00' * 8
    assert _infer_mime_from_bytes(data) == "image/gif"


def test_infer_webp():
    data = b'RIFF' + b'\x00' * 4 + b'WEBP' + b'\x00' * 4
    assert _infer_mime_from_bytes(data) == "image/webp"


def test_infer_jpeg():
    data = b'\xff\xd8\xff\xe0' + b'\x00' * 8
    assert _infer_mime_from_bytes(data) == "image/jpeg"


def test_infer_bmp():
    data = b'BM' + b'\x00' * 10
    assert _infer_mime_from_bytes(data) == "image/bmp"


def test_infer_unknown():
    data = b'\x00\x01\x02\x03\x04'
    assert _infer_mime_from_bytes(data) is None


def test_infer_short_data():
    assert _infer_mime_from_bytes(b'\x00\x01') is None


def test_infer_empty():
    assert _infer_mime_from_bytes(b'') is None


# ── check_base64 ────────────────────────────────────────────────────

def test_check_base64_valid():
    encoded = base64.b64encode(b"hello world").decode()
    assert check_base64(encoded) is True


def test_check_base64_invalid():
    assert check_base64("not!!!valid!!!base64!!!") is False


def test_check_base64_empty():
    assert check_base64("") is True


# ── Text / At / Reply / Emoji / Notice / Poke elements ─────────────

def test_text_element():
    t = Text("hello")
    assert t.type == ElementType.Text
    assert t.repr == "hello"


def test_at_element():
    a = At("123", nickname="Alice")
    assert a.type == ElementType.At
    assert a.repr == "[At Alice(123)]"


def test_at_element_no_nickname():
    a = At("456")
    assert a.repr == "[At 456]"


def test_reply_element():
    r = Reply("msg_001")
    assert r.type == ElementType.Reply
    assert r.repr == "[Reply msg_001]"


def test_emoji_element():
    e = Emoji("emoji_123", emoji_desc="smile")
    assert e.repr == "[Emoji smile(ID: emoji_123)]"


def test_emoji_element_no_desc():
    e = Emoji("emoji_123")
    assert e.repr == "[Emoji emoji_123]"


def test_notice_element():
    n = Notice("system notice")
    assert n.type == ElementType.Notice
    assert n.repr == "[Notice system notice]"


def test_poke_element():
    p = Poke("user_1")
    assert p.type == ElementType.Poke
    assert p.repr == "[Poke user_1]"


# ── Json element ────────────────────────────────────────────────────

def test_json_element():
    data = {"app": "com.tencent.miniapp_01", "title": "哔哩哔哩", "desc": "test"}
    j = Json(data)
    assert j.type == ElementType.Json
    assert j.data == data
    assert '"app": "com.tencent.miniapp_01"' in j.repr
    assert '"title": "哔哩哔哩"' in j.repr


def test_json_element_rejects_non_dict():
    with pytest.raises(TypeError, match="Json expects a dict"):
        Json("not a dict")


# ── BaseMediaElement.check_file_type ────────────────────────────────

def test_check_file_type_url():
    img = Image("https://example.com/pic.png")
    assert img.file_type == "url"


def test_check_file_type_data_url():
    img = Image("data:image/png;base64,AAAA")
    assert img.file_type == "data_url"


def test_check_file_type_base64_prefix():
    b64 = base64.b64encode(b"test").decode()
    img = Image(f"base64://{b64}")
    assert img.file_type == "base64"


def test_check_file_type_file_url():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)
        tmp_path = tmp.name
    try:
        img = Image(f"file:///{tmp_path}")
        assert img.file_type == "path"
    finally:
        os.unlink(tmp_path)


def test_check_file_type_local_path():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)
        tmp_path = tmp.name
    try:
        img = Image(tmp_path)
        assert img.file_type == "path"
    finally:
        os.unlink(tmp_path)


def test_check_file_type_unknown_raises():
    with pytest.raises(ValueError, match="Unknown file type"):
        Image("not_a_real_file_xyz")


# ── BaseMediaElement._guess_mime ────────────────────────────────────

def test_guess_mime_from_data_url():
    img = Image("data:image/png;base64,AAAA")
    assert img.mime == "image/png"


def test_guess_mime_from_url_extension():
    img = Image("https://example.com/photo.jpg")
    assert img.mime == "image/jpeg"


def test_base64_mime_left_unknown_until_use():
    b64 = base64.b64encode(b"random").decode()
    img = Image(f"base64://{b64}")
    assert img.mime is None


# ── BaseMediaElement.guess_name ─────────────────────────────────────

def test_guess_name_explicit():
    img = Image("https://example.com/a.png", name="my_photo.png")
    assert img.guess_name() == "my_photo.png"


def test_guess_name_from_url():
    img = Image("https://example.com/path/to/image.png")
    assert img.guess_name() == "image.png"


# ── Image element ───────────────────────────────────────────────────

def test_image_repr():
    img = Image("https://example.com/pic.png")
    assert img.repr == "[Image]"


@pytest.mark.asyncio
async def test_image_data_url_falls_back_to_jpeg():
    b64 = base64.b64encode(b"random").decode()
    img = Image(f"base64://{b64}")
    data_url = await img.to_data_url()
    assert data_url.startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_to_data_url_sniffs_real_format_from_base64():
    png_b64 = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16).decode()
    img = Image(f"base64://{png_b64}")
    data_url = await img.to_data_url()
    assert data_url.startswith("data:image/png;base64,")
    assert img.mime == "image/png"


@pytest.mark.asyncio
async def test_to_base64_sniffs_real_format_from_base64():
    gif_b64 = base64.b64encode(b'GIF89a' + b'\x00' * 16).decode()
    img = Image(f"base64://{gif_b64}")
    assert await img.to_base64() == gif_b64
    assert img.mime == "image/gif"


@pytest.mark.asyncio
async def test_to_path_records_content_type_for_extensionless_url(tmp_path, monkeypatch):
    monkeypatch.setattr("core.chat.message_elements.get_data_path", lambda: tmp_path)
    png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16

    class FakeResponse:
        headers = {"Content-Type": "image/png"}

    async def fake_download_file(url, path, *args, **kwargs):
        with open(path, "wb") as f:
            f.write(png_bytes)
        return FakeResponse()

    monkeypatch.setattr("core.chat.message_elements.download_file", fake_download_file)
    img = Image("https://multimedia.example.com/download?fid=abc&rkey=xyz")
    assert img.mime is None

    file_path = await img.to_path()

    assert img.mime == "image/png"
    assert file_path.endswith(".png")
    with open(file_path, "rb") as f:
        assert f.read() == png_bytes


# ── Sticker element ─────────────────────────────────────────────────

def test_sticker_repr_with_id():
    s = Sticker(sticker_id="abc", sticker="https://example.com/s.png")
    assert s.repr == "[Sticker abc]"


def test_sticker_repr_no_id():
    s = Sticker(sticker="https://example.com/s.png")
    assert s.repr == "[Sticker]"


# ── Record element ──────────────────────────────────────────────────

def test_record_repr():
    r = Record(record="https://example.com/audio.mp3")
    assert r.repr == "[Record]"


# ── File element ────────────────────────────────────────────────────

def test_file_repr_with_name():
    f = File(file="https://example.com/doc.pdf", name="doc.pdf")
    assert f.repr == "[File doc.pdf]"


def test_file_repr_no_name():
    f = File(file="https://example.com/file")
    assert f.repr == "[File]"


# ── Video element ───────────────────────────────────────────────────

def test_video_repr_with_name():
    v = Video(file="https://example.com/vid.mp4", name="vid.mp4")
    assert v.repr == "[Video vid.mp4]"


# ── Element __repr__ ────────────────────────────────────────────────

def test_element_dunder_repr():
    t = Text("hello")
    assert repr(t) == "Text(hello)"

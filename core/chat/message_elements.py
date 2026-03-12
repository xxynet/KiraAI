from __future__ import annotations

from typing import Optional, Union, Literal, TYPE_CHECKING
from abc import ABC, abstractmethod
from enum import Enum
import hashlib
import uuid
import base64
import os
import re
import mimetypes
from urllib.parse import urlparse, unquote

from core.utils.path_utils import get_data_path
from core.utils.network import download_file, get_file_content
from core.logging_manager import get_logger

if TYPE_CHECKING:
    from .message_utils import MessageChain

logger = get_logger("message", "cyan")


def _build_temp_file_path(name: Optional[str], mime: Optional[str]) -> str:
    base_dir = os.path.join(str(get_data_path()), "temp")
    if name:
        base_name = os.path.basename(name)
    else:
        base_name = uuid.uuid4().hex[:8]
    root, ext = os.path.splitext(base_name)
    if mime and not ext:
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            base_name = base_name + guessed
    return os.path.join(base_dir, base_name)


class ElementType(Enum):
    Text = "text"
    Image = "image"
    At = "at"
    Reply = "reply"
    Forward = "forward"
    Emoji = "emoji"
    Sticker = "sticker"
    Record = "record"
    Notice = "notice"
    Poke = "poke"
    File = "file"
    Video = "video"


def check_base64(s: str) -> bool:
    try:
        import base64
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False


class BaseMessageElement(ABC):
    type: ElementType

    @property
    @abstractmethod
    def repr(self) -> str:
        """Returns a string to display in logs"""
        pass


class Text(BaseMessageElement):
    type = ElementType.Text

    def __init__(self, text: str):
        self.text = text

    @property
    def repr(self) -> str:
        return self.text


class At(BaseMessageElement):
    """set pid to 'all' to at all group members"""
    type = ElementType.At

    def __init__(self, pid: Union[str, int], nickname: Optional[str] = None):
        self.pid = str(pid)
        self.nickname = nickname

    @property
    def repr(self) -> str:
        if self.nickname:
            return f"[At {self.nickname}({self.pid})]"
        return f"[At {self.pid}]"


class Reply(BaseMessageElement):
    type = ElementType.Reply

    def __init__(self, message_id: Union[str, int], message_content: Optional[str] = None, chain: Optional["MessageChain"] = None):
        self.message_id = str(message_id)
        self.message_content: str = message_content
        self.chain: "MessageChain" = chain

    @property
    def repr(self) -> str:
        return f"[Reply {self.message_id}]"


class Forward(BaseMessageElement):
    type = ElementType.Forward

    def __init__(self, chains: list[MessageChain] = None, message_id: Optional[str] = None):
        self.chains: list[MessageChain] = chains or []
        self.message_id = message_id

    @property
    def repr(self) -> str:
        if self.message_id:
            return f"[Forward] ID: {self.message_id}"
        return f"[Forward]"


class Emoji(BaseMessageElement):
    type = ElementType.Emoji

    def __init__(self, emoji_id: Union[str, int], emoji_desc: Optional[str] = None):
        self.emoji_id = str(emoji_id)
        self.emoji_desc = emoji_desc

    @property
    def repr(self) -> str:
        if self.emoji_desc:
            return f"[Emoji {self.emoji_desc}(ID: {self.emoji_id})]"
        return f"[Emoji {self.emoji_id}]"


class BaseMediaElement(BaseMessageElement, ABC):
    def __init__(self, file: str, name: str = None, size: str = None, mime: Optional[str] = None):
        self.name: str = name
        self.size: str = size  # Bytes
        self.file = file
        self._temp_path: Optional[str] = None
        self.file_type: Literal["url", "path", "base64", "data_url"] = self.check_file_type()
        self.mime: Optional[str] = mime or self._guess_mime()

    def check_file_type(self) -> Literal["url", "path", "base64", "data_url"]:
        # 1 http(s) URL
        if self.file.startswith(("http://", "https://")):
            return "url"

        # 2 Data URL
        if self.file.startswith("data:"):
            return "data_url"

        # 3 file:// URL
        if self.file.startswith("file:///"):
            self.file = self.file.removeprefix("file:///")
            return "path"

        # 4 Local path
        if os.path.exists(self.file):
            return "path"

        # 5 base64
        if self.file.startswith("base64://"):
            self.file = self.file.removeprefix("base64://")
            return "base64"

        if check_base64(self.file):
            return "base64"

        raise ValueError(f"Unknown file type: {self.file!r}")

    def _guess_mime(self) -> Optional[str]:
        if self.file_type == "data_url" and self.file.startswith("data:"):
            header = self.file[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part
        if self.name:
            mime, _ = mimetypes.guess_type(self.name)
            if mime:
                return mime
        if self.file_type == "path":
            mime, _ = mimetypes.guess_type(self.file)
            if mime:
                return mime
        if self.file_type == "url":
            parsed = urlparse(self.file)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime
        return None

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp file {self._temp_path}: {e}")


class Image(BaseMessageElement):
    type = ElementType.Image

    def __init__(self, image: str, mime: Optional[str] = None, name: Optional[str] = None):
        """
        :param image: image data in "url", "path", "base64", "data_url"
        """
        self.image: str = image
        self.name: Optional[str] = name
        self.caption: Optional[str] = ""
        self.md5: Optional[str] = None
        self._temp_path: Optional[str] = None
        self.image_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_image_type()
        self._mime_explicit = mime is not None
        if mime is not None:
            self.mime: str = mime
        else:
            guessed = self._guess_mime()
            self.mime: str = guessed if guessed else "image/jpeg"

    def check_image_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.image
        if not value:
            return "unknown"
        if value.startswith(("http://", "https://")):
            return "url"
        if value.startswith("data:"):
            if not self.image:
                self.image = value
            return "data_url"
        if value.startswith("file:///"):
            path = value.removeprefix("file:///")
            self.image = path
            return "path"
        if os.path.exists(value):
            self.image = value
            return "path"
        b64_str = value
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        if check_base64(b64_str):
            return "base64"
        return "unknown"

    def _guess_mime(self) -> Optional[str]:
        value = self.image or ""
        if self.image_type == "data_url" and value.startswith("data:"):
            header = value[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part
        if self.image_type == "path" and self.image:
            mime, _ = mimetypes.guess_type(self.image)
            if mime:
                return mime
        if self.image_type == "url" and self.image:
            parsed = urlparse(self.image)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime
        return None

    def guess_name(self) -> Optional[str]:
        if self.name:
            return self.name
        if self.image_type == "path" and self.image:
            return os.path.basename(self.image)
        if self.image_type == "url" and self.image:
            parsed = urlparse(self.image)
            return os.path.basename(parsed.path)
        return None

    async def hash_image(self):
        if self.md5:
            return self.md5
        if self.image and self.image_type == "base64":
            md5 = await self._hash_image_from_base64()
            self.md5 = md5
            return md5
        if self.image and self.type == "url":
            return await self._hash_image_from_url()
        if self.image and os.path.exists(self.image):
            with open(self.image, "rb") as f:
                data = f.read()
            h = hashlib.new("md5")
            h.update(data)
            md5 = h.hexdigest()
            self.md5 = md5
            return md5
        raise ValueError("No image data available to hash")

    async def _hash_image_from_url(self):
        image_data = await get_file_content(self.image)
        h = hashlib.new("md5")
        h.update(image_data)
        md5 = h.hexdigest()
        self.md5 = md5
        return md5

    async def _hash_image_from_base64(self):
        if not self.image:
            raise ValueError("No base64 data for image")
        b64_str = self.image
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        self.image = b64_str
        image_bytes = base64.b64decode(b64_str)
        h = hashlib.new("md5")
        h.update(image_bytes)
        md5 = h.hexdigest()
        self.md5 = md5
        return md5

    async def to_path(self):
        if self.image_type == "path" and self.image:
            return os.path.abspath(self.image)
        if self._temp_path:
            return self._temp_path
        if not self.name:
            guessed_name = self.guess_name()
            if guessed_name:
                self.name = guessed_name
        file_path = _build_temp_file_path(self.name, self.mime)
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.image_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.image_type == "url" and self.image:
            resp = await download_file(self.image, file_path)
            if self.name is None:
                filename = None
                content_disposition = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                if content_disposition:
                    match_ext = re.search(r'filename\*=([^;]+)', content_disposition, re.IGNORECASE)
                    if match_ext:
                        value = match_ext.group(1).strip()
                        if "''" in value:
                            value = value.split("''", 1)[1]
                        filename = unquote(value.strip(' "'))
                    else:
                        match = re.search(r'filename=([^;]+)', content_disposition, re.IGNORECASE)
                        if match:
                            value = match.group(1).strip()
                            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                            filename = value
                if not filename:
                    value = self.image
                    if value:
                        parsed = urlparse(value)
                        filename = os.path.basename(parsed.path)
                if filename:
                    desired_path = _build_temp_file_path(filename, self.mime)
                    if desired_path != file_path:
                        try:
                            os.replace(file_path, desired_path)
                            file_path = desired_path
                            self._temp_path = desired_path
                        except Exception:
                            pass
                    self.name = filename
            if not self._mime_explicit:
                content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                if content_type:
                    self.mime = content_type.split(";", 1)[0].strip()
            return file_path
        return file_path

    async def to_base64(self) -> str:
        if self.image_type == "base64" and self.image is not None:
            return self.image
        if self.image_type == "data_url" and self.image is not None:
            try:
                return self.image.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.image_type == "path" and self.image is not None:
            with open(self.image, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.image_type == "url" and self.image is not None:
            data = await get_file_content(self.image)
            return base64.b64encode(data).decode()
        if self.image:
            return self.image
        return ""

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp image {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        return "[Image]"


class Sticker(BaseMessageElement):
    type = ElementType.Sticker

    def __init__(
        self,
        sticker_id: Optional[Union[str, int]] = None,
        sticker: Optional[str] = None,
        mime: Optional[str] = None,
    ):
        self.sticker_id = str(sticker_id) if sticker_id is not None else None
        self.sticker = sticker
        self.caption: str = ""
        self._temp_path: Optional[str] = None
        self.sticker_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_sticker_type()
        self.mime: Optional[str] = mime or self._guess_mime()

    def check_sticker_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.sticker
        if not value:
            return "unknown"
        if value.startswith(("http://", "https://")):
            self.sticker = value
            return "url"
        if value.startswith("data:"):
            if not self.sticker:
                self.sticker = value
            return "data_url"
        if value.startswith("file:///"):
            path = value.removeprefix("file:///")
            self.sticker = path
            return "path"
        if os.path.exists(value):
            self.sticker = value
            return "path"
        b64_str = value
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        if check_base64(b64_str):
            return "base64"
        return "unknown"

    def _guess_mime(self) -> Optional[str]:
        value = self.sticker or ""
        if self.sticker_type == "data_url" and value.startswith("data:"):
            header = value[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part
        if self.sticker_type == "path" and self.sticker:
            mime, _ = mimetypes.guess_type(self.sticker)
            if mime:
                return mime
        if self.sticker_type == "url" and self.sticker:
            parsed = urlparse(self.sticker)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime
        return None

    async def to_path(self):
        if self.sticker_type == "path" and self.sticker:
            return os.path.abspath(self.sticker)
        sticker_name = None
        if self.sticker_type == "url" and self.sticker:
            parsed = urlparse(self.sticker)
            sticker_name = os.path.basename(parsed.path)
        file_path = _build_temp_file_path(sticker_name, self.mime)
        if self._temp_path:
            return self._temp_path
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.sticker_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.sticker_type == "url" and self.sticker:
            resp = await download_file(self.sticker, file_path)
            if self.mime is None:
                content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                if content_type:
                    self.mime = content_type.split(";", 1)[0].strip()
            return file_path
        return file_path

    async def to_base64(self) -> str:
        if self.sticker_type == "base64" and self.sticker is not None:
            return self.sticker
        if self.sticker_type == "data_url" and self.sticker is not None:
            try:
                return self.sticker.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.sticker_type == "path" and self.sticker is not None:
            with open(self.sticker, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.sticker_type == "url" and self.sticker is not None:
            data = await get_file_content(self.sticker)
            return base64.b64encode(data).decode()
        if self.sticker:
            return self.sticker
        return ""

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp sticker {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        if not self.sticker_id:
            return "[Sticker]"
        return f"[Sticker {self.sticker_id}]"


class Record(BaseMessageElement):
    type = ElementType.Record

    def __init__(self, record: Optional[str], mime: Optional[str] = None, name: Optional[str] = None):
        self.record: str = record
        self.name: Optional[str] = name
        self.transcript: Optional[str] = ""
        self._temp_path: Optional[str] = None
        self.record_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_record_type()
        self.mime: Optional[str] = mime or self._guess_mime()

    def check_record_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.record
        if not value:
            return "unknown"
        if value.startswith(("http://", "https://")):
            return "url"
        if value.startswith("data:"):
            return "data_url"
        if value.startswith("file:///"):
            path = value.removeprefix("file:///")
            self.record = path
            return "path"
        if os.path.exists(value):
            return "path"
        b64_str = value
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        if check_base64(b64_str):
            return "base64"
        return "unknown"

    def _guess_mime(self) -> Optional[str]:
        value = self.record
        if self.record_type == "data_url" and value.startswith("data:"):
            header = value[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part
        if self.record_type == "path":
            mime, _ = mimetypes.guess_type(value)
            if mime:
                return mime
        if self.record_type == "url":
            parsed = urlparse(value)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime
        return None

    def guess_name(self) -> Optional[str]:
        if self.name:
            return self.name
        if self.record_type == "path":
            return os.path.basename(self.record)
        if self.record_type == "url":
            parsed = urlparse(self.record)
            return os.path.basename(parsed.path)
        return None

    async def to_path(self):
        if self.record_type == "path":
            return os.path.abspath(self.record)
        if self._temp_path:
            return self._temp_path
        if not self.name:
            guessed_name = self.guess_name()
            if guessed_name:
                self.name = guessed_name
        file_path = _build_temp_file_path(self.name, self.mime)
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.record_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.record_type == "url":
            resp = await download_file(self.record, file_path)
            if self.name is None:
                filename = None
                content_disposition = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                if content_disposition:
                    match_ext = re.search(r'filename\*=([^;]+)', content_disposition, re.IGNORECASE)
                    if match_ext:
                        value = match_ext.group(1).strip()
                        if "''" in value:
                            value = value.split("''", 1)[1]
                        filename = unquote(value.strip(' "'))
                    else:
                        match = re.search(r'filename=([^;]+)', content_disposition, re.IGNORECASE)
                        if match:
                            value = match.group(1).strip()
                            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                            filename = value
                if not filename:
                    parsed = urlparse(self.record)
                    filename = os.path.basename(parsed.path)
                if filename:
                    desired_path = _build_temp_file_path(filename, self.mime)
                    if desired_path != file_path:
                        try:
                            os.replace(file_path, desired_path)
                            file_path = desired_path
                            self._temp_path = desired_path
                        except Exception:
                            pass
                    self.name = filename
            if self.mime is None:
                content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                if content_type:
                    self.mime = content_type.split(";", 1)[0].strip()
            return file_path
        return file_path

    async def to_base64(self) -> str:
        if self.record_type == "base64":
            return self.record
        if self.record_type == "data_url":
            try:
                return self.record.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.record_type == "path":
            with open(self.record, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.record_type == "url":
            data = await get_file_content(self.record)
            return base64.b64encode(data).decode()
        return self.record

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp record {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        return "[Record]"


class Notice(BaseMessageElement):
    type = ElementType.Notice

    def __init__(self, text: str):
        self.text = text

    @property
    def repr(self) -> str:
        return f"[Notice {self.text}]"


class Poke(BaseMessageElement):
    type = ElementType.Poke

    def __init__(self, pid: Union[str, int]):
        self.pid = str(pid)

    @property
    def repr(self) -> str:
        return f"[Poke {self.pid}]"


class File(BaseMessageElement):
    """File object, could be url, local or base64"""
    type = ElementType.File

    def __init__(self, file: str, name: str = None, size: str = None, mime: Optional[str] = None):
        self.name: str = name
        self.size: str = size  # Bytes
        self.file = file
        self.description: Optional[str] = ""
        self._temp_path: Optional[str] = None
        self.file_type: Literal["url", "path", "base64", "data_url"] = self.check_file_type()
        self.mime: Optional[str] = mime or self._guess_mime()

    def check_file_type(self) -> Literal["url", "path", "base64", "data_url"]:
        # 1 http(s) URL
        if self.file.startswith(("http://", "https://")):
            return "url"

        # 2 Data URL
        if self.file.startswith("data:"):
            return "data_url"

        # 3 file:// URL
        if self.file.startswith("file:///"):
            self.file = self.file.removeprefix("file:///")
            return "path"

        # 4 Local path
        if os.path.exists(self.file):
            return "path"

        # 5 base64
        if self.file.startswith("base64://"):
            self.file = self.file.removeprefix("base64://")
            return "base64"

        if check_base64(self.file):
            return "base64"

        raise ValueError(f"Unknown file type: {self.file!r}")

    def _guess_mime(self) -> Optional[str]:
        if self.file_type == "data_url" and self.file.startswith("data:"):
            header = self.file[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part
        if self.name:
            mime, _ = mimetypes.guess_type(self.name)
            if mime:
                return mime
        if self.file_type == "path":
            mime, _ = mimetypes.guess_type(self.file)
            if mime:
                return mime
        if self.file_type == "url":
            parsed = urlparse(self.file)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime
        return None

    async def to_path(self):
        if self.file_type == "path":
            return os.path.abspath(self.file)

        if self.file_type == "url":
            file_path = _build_temp_file_path(self.name, self.mime)
            if self._temp_path:
                return self._temp_path
            self._temp_path = file_path
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            try:
                resp = await download_file(self.file, file_path)
                if self.name is None:
                    filename = None
                    content_disposition = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                    if content_disposition:
                        match_ext = re.search(r'filename\*=([^;]+)', content_disposition, re.IGNORECASE)
                        if match_ext:
                            value = match_ext.group(1).strip()
                            if "''" in value:
                                value = value.split("''", 1)[1]
                            filename = unquote(value.strip(' "'))
                        else:
                            match = re.search(r'filename=([^;]+)', content_disposition, re.IGNORECASE)
                            if match:
                                value = match.group(1).strip()
                                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                                    value = value[1:-1]
                                filename = value
                    if not filename:
                        parsed = urlparse(self.file)
                        filename = os.path.basename(parsed.path)
                    if filename:
                        self.name = filename
                if self.mime is None:
                    content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                    if content_type:
                        self.mime = content_type.split(";", 1)[0].strip()
                if self.name:
                    desired_path = _build_temp_file_path(self.name, self.mime)
                    if desired_path != file_path:
                        try:
                            os.replace(file_path, desired_path)
                            file_path = desired_path
                            self._temp_path = desired_path
                        except Exception as e:
                            logger.warning(
                                f"[File.to_path] failed to rename temp file {file_path!r} "
                                f"to {desired_path!r}: {e}"
                            )
            except Exception as e:
                raise
            return file_path

        if self.file_type in ("base64", "data_url"):
            file_path = _build_temp_file_path(self.name, self.mime)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))

            return file_path

    async def to_base64(self) -> str:
        """
        Return raw base64 string (no prefix, no data URL header)
        """
        # Already base64
        if self.file_type == "base64":
            return self.file

        # Data URL → base64
        if self.file_type == "data_url":
            # data:image/png;base64,xxxx
            try:
                return self.file.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")

        # Local file → base64
        if self.file_type == "path":
            with open(self.file, "rb") as f:
                return base64.b64encode(f.read()).decode()

        # URL → download → base64
        if self.file_type == "url":
            path = await self.to_path()
            with open(path, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode()
            os.remove(path)
            return b64_str

        raise RuntimeError(f"Unsupported file_type: {self.file_type}")

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp file {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        if self.name:
            return f"[File {self.name}]"
        return "[File]"


class Video(BaseMessageElement):
    """Video object, could be url, local or base64"""
    type = ElementType.Video

    def __init__(self, file: str, name: str = None, size: str = None, mime: Optional[str] = None):
        self.name: str = name
        self.size: str = size  # Bytes
        self.file = file
        self._temp_path: Optional[str] = None
        self.file_type: Literal["url", "path", "base64", "data_url"] = self.check_file_type()
        self.mime: Optional[str] = mime or self._guess_mime()

    def check_file_type(self) -> Literal["url", "path", "base64", "data_url"]:
        if self.file.startswith(("http://", "https://")):
            return "url"

        if self.file.startswith("data:"):
            return "data_url"

        if self.file.startswith("file:///"):
            self.file = self.file.removeprefix("file:///")
            return "path"

        if os.path.exists(self.file):
            return "path"

        if self.file.startswith("base64://"):
            self.file = self.file.removeprefix("base64://")
            return "base64"

        if check_base64(self.file):
            return "base64"

        raise ValueError(f"Unknown file type: {self.file!r}")

    def _guess_mime(self) -> Optional[str]:
        if self.file_type == "data_url" and self.file.startswith("data:"):
            header = self.file[5:]
            type_part = header.split(";", 1)[0]
            if "/" in type_part:
                return type_part

        if self.name:
            mime, _ = mimetypes.guess_type(self.name)
            if mime:
                return mime

        if self.file_type == "path":
            mime, _ = mimetypes.guess_type(self.file)
            if mime:
                return mime

        if self.file_type == "url":
            parsed = urlparse(self.file)
            mime, _ = mimetypes.guess_type(parsed.path)
            if mime:
                return mime

        return None

    async def to_path(self):
        if self.file_type == "path":
            return os.path.abspath(self.file)

        if self.file_type == "url":
            file_path = _build_temp_file_path(self.name, self.mime)

            if self._temp_path:
                return self._temp_path

            self._temp_path = file_path
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            resp = await download_file(self.file, file_path)

            if self.name is None:
                filename = None
                content_disposition = (
                    resp.headers.get("Content-Disposition")
                    or resp.headers.get("content-disposition")
                )

                if content_disposition:
                    match_ext = re.search(r'filename\*=([^;]+)', content_disposition, re.IGNORECASE)
                    if match_ext:
                        value = match_ext.group(1).strip()
                        if "''" in value:
                            value = value.split("''", 1)[1]
                        filename = unquote(value.strip(' "'))
                    else:
                        match = re.search(r'filename=([^;]+)', content_disposition, re.IGNORECASE)
                        if match:
                            value = match.group(1).strip()
                            if (value.startswith('"') and value.endswith('"')) or (
                                value.startswith("'") and value.endswith("'")
                            ):
                                value = value[1:-1]
                            filename = value

                if not filename:
                    parsed = urlparse(self.file)
                    filename = os.path.basename(parsed.path)

                if filename:
                    self.name = filename

            if self.mime is None:
                content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                if content_type:
                    self.mime = content_type.split(";", 1)[0].strip()

            return file_path

        if self.file_type in ("base64", "data_url"):
            file_path = _build_temp_file_path(self.name, self.mime)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            b64 = await self.to_base64()

            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))

            return file_path

    async def to_base64(self) -> str:
        """
        Return raw base64 string (no prefix, no data URL header)
        """
        if self.file_type == "base64":
            return self.file

        if self.file_type == "data_url":
            try:
                return self.file.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")

        if self.file_type == "path":
            with open(self.file, "rb") as f:
                return base64.b64encode(f.read()).decode()

        if self.file_type == "url":
            path = await self.to_path()
            with open(path, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode()
            os.remove(path)
            return b64_str

        raise RuntimeError(f"Unsupported file_type: {self.file_type}")

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp file {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        if self.name:
            return f"[Video {self.name}]"
        return "[Video]"

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

    def __init__(self, chains: list[MessageChain] = None, message_id: Optional[str, list] = None, merge: bool = True):
        self.chains: list[MessageChain] = chains or []
        self.message_id = message_id
        self.merge: bool = merge

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

    def guess_name(self) -> Optional[str]:
        if self.name:
            return self.name
        if self.file_type == "path" and self.file:
            return os.path.basename(self.file)
        if self.file_type == "url" and self.file:
            parsed = urlparse(self.file)
            return os.path.basename(parsed.path)
        return None

    async def to_path(self):
        if self.file_type == "path" and self.file:
            return os.path.abspath(self.file)
        if self._temp_path:
            return self._temp_path
        if not self.name:
            guessed_name = self.guess_name()
            if guessed_name:
                self.name = guessed_name
        file_path = _build_temp_file_path(self.name, self.mime)
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.file_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.file_type == "url" and self.file:
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
                    value = self.file
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
            if not self.mime:
                content_type = resp.headers.get("Content-Type") or resp.headers.get("content-type")
                if content_type:
                    self.mime = content_type.split(";", 1)[0].strip()
            return file_path
        return file_path

    async def to_base64(self) -> str:
        """Better use to_path for large File or Video objects"""

        if self.file_type == "base64" and self.file is not None:
            return self.file
        if self.file_type == "data_url" and self.file is not None:
            try:
                return self.file.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.file_type == "path" and self.file is not None:
            with open(self.file, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.file_type == "url" and self.file is not None:
            data = await get_file_content(self.file)
            return base64.b64encode(data).decode()
        if self.file:
            return self.file
        return ""

    async def to_data_url(self) -> str:
        """Convert media elements to Data URL

        Data URL format：data:[<mime>][;base64],<data>

        Returns:
            str: Data URL

        Raises:
            ValueError:
        """
        # If it's originally Data UR
        if self.file_type == "data_url" and self.file is not None:
            return self.file

        # Fetch base64 data
        base64_str = await self.to_base64()
        if not base64_str:
            raise ValueError("Failed to fetch base64 data")

        # Get MIME type
        mime = self.mime
        if not mime:
            # Judge default type by class name
            class_name = self.__class__.__name__.lower()
            if "image" in class_name:
                mime = "image/jpeg"  # Default image type
            elif "video" in class_name:
                mime = "video/mp4"  # Default video type
            elif "record" in class_name:
                mime = "audio/mpeg"  # Default audio type
            else:
                mime = "application/octet-stream"

        # Build Data URL
        data_url = f"data:{mime};base64,{base64_str}"

        return data_url

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
            self._temp_path = None
        except Exception as e:
            logger.warning(f"Failed to delete temp {self.__class__.__name__.lower()} {self._temp_path}: {e}")


class Image(BaseMediaElement):
    type = ElementType.Image

    def __init__(self, image: str, mime: Optional[str] = None, name: Optional[str] = None):
        """
        :param image: image data in "url", "path", "base64", "data_url"
        """
        super().__init__(file=image, name=name, mime=mime)
        self.image: str = self.file
        self.caption: Optional[str] = ""
        self.md5: Optional[str] = None
        self.image_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.file_type
        self.mime = self.mime or "image/jpeg"

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

    @property
    def repr(self) -> str:
        return "[Image]"


class Sticker(BaseMediaElement):
    type = ElementType.Sticker

    def __init__(
        self,
        sticker_id: Optional[Union[str, int]] = None,
        sticker: Optional[str] = None,
        mime: Optional[str] = None,
    ):
        super().__init__(file=sticker, mime=mime)
        self.sticker_id = str(sticker_id) if sticker_id is not None else None
        self.caption: str = ""

    @property
    def sticker(self):
        return self.file

    @property
    def sticker_type(self):
        return self.file_type

    @property
    def repr(self) -> str:
        if not self.sticker_id:
            return "[Sticker]"
        return f"[Sticker {self.sticker_id}]"


class Record(BaseMediaElement):
    type = ElementType.Record

    def __init__(self, record: Optional[str], mime: Optional[str] = None, name: Optional[str] = None):
        super().__init__(file=record, name=name, mime=mime)
        self.transcript: Optional[str] = ""

    @property
    def record(self):
        return self.file

    @property
    def record_type(self):
        return self.file_type

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


class File(BaseMediaElement):
    """File object, could be url, local or base64"""
    type = ElementType.File

    def __init__(self, file: str, name: str = None, size: str = None, mime: Optional[str] = None):
        super().__init__(file=file, name=name, size=size, mime=mime)
        self.description: Optional[str] = ""

    @property
    def repr(self) -> str:
        if self.name:
            return f"[File {self.name}]"
        return "[File]"


class Video(BaseMediaElement):
    """Video object, could be url, local or base64"""
    type = ElementType.Video

    def __init__(self, file: str, name: str = None, size: str = None, mime: Optional[str] = None):
        super().__init__(file=file, name=name, size=size, mime=mime)

    @property
    def repr(self) -> str:
        if self.name:
            return f"[Video {self.name}]"
        return "[Video]"

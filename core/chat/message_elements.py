from typing import Optional, Union, Literal
from pydantic import BaseModel, model_validator
from abc import ABC, abstractmethod
from enum import Enum
import uuid
import base64
import os

from core.utils.path_utils import get_data_path
from core.utils.download import download_file


class ElementType(Enum):
    Text = "text"
    Image = "image"
    At = "at"
    Reply = "reply"
    Emoji = "emoji"
    Sticker = "sticker"
    Record = "record"
    Notice = "notice"
    Poke = "poke"
    File = "file"


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


class Image(BaseMessageElement):
    type = ElementType.Image

    def __init__(self, url: Optional[str] = None, base64: Optional[str] = None):
        self.url = url
        self.base64 = base64

    @property
    def repr(self) -> str:
        return "[Image]"


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

    def __init__(self, message_id: Union[str, int], message_content: Optional[str] = None):
        self.message_id = str(message_id)
        self.message_content = message_content

    @property
    def repr(self) -> str:
        return f"[Reply {self.message_id}]"


class Emoji(BaseMessageElement):
    type = ElementType.Emoji

    def __init__(self, emoji_id: Union[str, int]):
        self.emoji_id = str(emoji_id)

    @property
    def repr(self) -> str:
        return f"[Emoji {self.emoji_id}]"


class Sticker(BaseMessageElement):
    type = ElementType.Sticker

    def __init__(
        self,
        sticker_id: Optional[Union[str, int]] = None,
        sticker_bs64: Optional[str] = None,
    ):
        self.sticker_id = str(sticker_id) if sticker_id is not None else None
        self.sticker_bs64 = sticker_bs64

    @property
    def repr(self) -> str:
        return f"[Sticker {self.sticker_id}]"


class Record(BaseMessageElement):
    type = ElementType.Record

    def __init__(self, bs64: str):
        self.bs64 = bs64

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
        return "[Poke]"


class File(BaseMessageElement):
    """File object, could be url, local or base64"""
    type = ElementType.File

    def __init__(self, file: str, name: str = None, size: str = None):
        self.name: str = name
        self.size: str = size  # Bytes
        self.file = file
        self.file_type: Literal["url", "path", "base64", "data_url"] = self.check_file_type()

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

        if self._check_base64(self.file):
            return "base64"

        raise ValueError(f"Unknown file type: {self.file!r}")

    @staticmethod
    def _check_base64(s: str) -> bool:
        try:
            import base64
            base64.b64decode(s, validate=True)
            return True
        except Exception:
            return False

    async def to_path(self):
        if self.file_type == "path":
            return os.path.abspath(self.file)

        if self.file_type == "url":
            file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            try:
                await download_file(self.file, file_path)
            except Exception as e:
                raise
            return file_path

        if self.file_type in ("base64", "data_url"):
            file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"
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

    @property
    def repr(self) -> str:
        return "[File]"

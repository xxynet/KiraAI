from typing import Optional, Union, Literal, TYPE_CHECKING
from abc import ABC, abstractmethod
from enum import Enum
import hashlib
import uuid
import base64
import os

from core.utils.path_utils import get_data_path
from core.utils.network import download_file, get_file_content
from core.logging_manager import get_logger

if TYPE_CHECKING:
    from .message_utils import MessageChain

logger = get_logger("message", "cyan")


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


class Image(BaseMessageElement):
    type = ElementType.Image

    def __init__(self, url: Optional[str] = None, b64: Optional[str] = None, image: Optional[str] = None):
        """
        :param url: Backward compatibility
        :param b64: Backward compatibility
        :param image: image data in "url", "path", "base64", "data_url"
        """
        self.image: Optional[str] = image
        self.url: Optional[str] = url
        self.base64: Optional[str] = b64
        self.md5: Optional[str] = None
        self._temp_path: Optional[str] = None
        self.image_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_image_type()

    def check_image_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.image or self.url or self.base64
        if not value:
            return "unknown"
        if value.startswith(("http://", "https://")):
            self.url = value
            return "url"
        if value.startswith("data:"):
            if not self.image:
                self.image = value
            return "data_url"
        if value.startswith("file:///"):
            path = value.removeprefix("file:///")
            self.image = path
            self.url = None
            return "path"
        if os.path.exists(value):
            self.image = value
            self.url = None
            return "path"
        b64_str = value
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        if check_base64(b64_str):
            self.base64 = b64_str
            return "base64"
        return "unknown"

    async def hash_image(self):
        if self.md5:
            return self.md5
        if self.base64:
            md5 = await self._hash_image_from_base64()
            self.md5 = md5
            return md5
        if self.url:
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
        image_data = await get_file_content(self.url)
        h = hashlib.new("md5")
        h.update(image_data)
        md5 = h.hexdigest()
        self.md5 = md5
        return md5

    async def _hash_image_from_base64(self):
        if not self.base64:
            raise ValueError("No base64 data for image")
        b64_str = self.base64
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        self.base64 = b64_str
        image_bytes = base64.b64decode(b64_str)
        h = hashlib.new("md5")
        h.update(image_bytes)
        md5 = h.hexdigest()
        self.md5 = md5
        return md5

    async def to_path(self):
        if self.image_type == "path" and self.image:
            return os.path.abspath(self.image)
        file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.image_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.image_type == "url" and self.image:
            await download_file(self.image, file_path)
            return file_path
        if self.base64:
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(self.base64))
            return file_path
        return file_path

    async def to_base64(self) -> str:
        if self.image_type == "base64" and self.base64 is not None:
            return self.base64
        if self.image_type == "data_url" and self.image:
            try:
                return self.image.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.image_type == "path" and self.image:
            with open(self.image, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.image_type == "url" and self.image:
            data = await get_file_content(self.image)
            return base64.b64encode(data).decode()
        if self.base64 is not None:
            return self.base64
        if self.image:
            return self.image
        return ""

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp image {self._temp_path}: {e}")

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

    def __init__(self, message_id: Union[str, int], message_content: Optional[str] = None, chain: Optional["MessageChain"] = None):
        self.message_id = str(message_id)
        self.message_content: str = message_content
        self.chain: "MessageChain" = chain

    @property
    def repr(self) -> str:
        return f"[Reply {self.message_id}]"


class Forward(BaseMessageElement):
    type = ElementType.Forward

    def __init__(self, chains: list["MessageChain"]):
        self.chains: list["MessageChain"] = chains or []

    @property
    def repr(self) -> str:
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


class Sticker(BaseMessageElement):
    type = ElementType.Sticker

    def __init__(
        self,
        sticker_id: Optional[Union[str, int]] = None,
        sticker_bs64: Optional[str] = None,
        sticker: Optional[str] = None,
    ):
        self.sticker_id = str(sticker_id) if sticker_id is not None else None
        self.sticker = sticker
        self.sticker_bs64 = sticker_bs64
        self._temp_path: Optional[str] = None
        self.sticker_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_sticker_type()

    def check_sticker_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.sticker or self.sticker_bs64
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
            self.sticker_bs64 = b64_str
            return "base64"
        return "unknown"

    async def to_path(self):
        if self.sticker_type == "path" and self.sticker:
            return os.path.abspath(self.sticker)
        file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"
        self._temp_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.sticker_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.sticker_type == "url" and self.sticker:
            await download_file(self.sticker, file_path)
            return file_path
        if self.sticker_bs64:
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(self.sticker_bs64))
            return file_path
        return file_path

    async def to_base64(self) -> str:
        if self.sticker_type == "base64" and self.sticker_bs64 is not None:
            return self.sticker_bs64
        if self.sticker_type == "data_url" and self.sticker:
            try:
                return self.sticker.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.sticker_type == "path" and self.sticker:
            with open(self.sticker, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.sticker_type == "url" and self.sticker:
            data = await get_file_content(self.sticker)
            return base64.b64encode(data).decode()
        if self.sticker_bs64 is not None:
            return self.sticker_bs64
        if self.sticker:
            return self.sticker
        return ""

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp sticker {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        if not self.sticker_id:
            return "[Sticker]"
        return f"[Sticker {self.sticker_id}]"


class Record(BaseMessageElement):
    type = ElementType.Record

    def __init__(self, bs64: str):
        self.bs64 = bs64
        self._temp_path: Optional[str] = None
        self.record_type: Literal["url", "path", "base64", "data_url", "unknown"] = self.check_record_type()

    def check_record_type(self) -> Literal["url", "path", "base64", "data_url", "unknown"]:
        value = self.bs64
        if not value:
            return "unknown"
        if value.startswith(("http://", "https://")):
            return "url"
        if value.startswith("data:"):
            return "data_url"
        if value.startswith("file:///"):
            path = value.removeprefix("file:///")
            self.bs64 = path
            return "path"
        if os.path.exists(value):
            return "path"
        b64_str = value
        if b64_str.startswith("base64://"):
            b64_str = b64_str[9:]
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        if check_base64(b64_str):
            self.bs64 = b64_str
            return "base64"
        return "unknown"

    async def to_path(self):
        if self.record_type == "path":
            return os.path.abspath(self.bs64)
        file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"

        self._temp_path = file_path

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if self.record_type in ("base64", "data_url"):
            b64 = await self.to_base64()
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            return file_path
        if self.record_type == "url":
            await download_file(self.bs64, file_path)
            return file_path
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(self.bs64))
        return file_path

    async def to_base64(self) -> str:
        if self.record_type == "base64":
            return self.bs64
        if self.record_type == "data_url":
            try:
                return self.bs64.split(",", 1)[1]
            except IndexError:
                raise ValueError("Invalid data URL")
        if self.record_type == "path":
            with open(self.bs64, "rb") as f:
                return base64.b64encode(f.read()).decode()
        if self.record_type == "url":
            data = await get_file_content(self.bs64)
            return base64.b64encode(data).decode()
        return self.bs64

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
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
        return "[Poke]"


class File(BaseMessageElement):
    """File object, could be url, local or base64"""
    type = ElementType.File

    def __init__(self, file: str, name: str = None, size: str = None):
        self.name: str = name
        self.size: str = size  # Bytes
        self.file = file
        self._temp_path: Optional[str] = None
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

        if check_base64(self.file):
            return "base64"

        raise ValueError(f"Unknown file type: {self.file!r}")

    async def to_path(self):
        if self.file_type == "path":
            return os.path.abspath(self.file)

        if self.file_type == "url":
            file_path = f"{get_data_path()}/temp/{uuid.uuid4().hex}"
            self._temp_path = file_path
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

    def del_cache(self):
        if not self._temp_path:
            return
        try:
            os.remove(self._temp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temp file {self._temp_path}: {e}")

    @property
    def repr(self) -> str:
        if self.name:
            return f"[File {self.name}]"
        return "[File]"

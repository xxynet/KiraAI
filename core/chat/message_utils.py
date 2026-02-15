from dataclasses import dataclass, field
from enum import Enum
from typing import Union, Optional, Literal

from core.chat.message_elements import (
    Text,
    Image,
    At,
    Reply,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke,
    File
)

from .session import Session, Group, User
from core.adapter.adapter_info import AdapterInfo


class MessageType(Enum):
    GroupMsg =  "gm"
    DirectMsg = "dm"
    SystemMsg = "sm"


@dataclass
class KiraMessageEvent:
    message_types: list
    message_id: str
    self_id: str
    chain: list
    timestamp: int
    process_strategy: Literal["default", "buffer", "discard"] = "default"
    adapter: AdapterInfo = None
    sender: User = None
    session: Session = None
    group: Group = None
    is_notice: bool = False
    is_mentioned: Optional[bool] = None
    message_str: Optional[str] = field(default=None, init=False)
    message_repr: Optional[str] = field(default=None, init=False)
    _is_stopped: bool = False

    def __post_init__(self):
        self.message_repr = " ".join(ele.repr for ele in self.chain)
        self.session = Session(
            adapter_name=self.adapter.name,
            session_type="gm" if self.group else "dm",
            session_id=self.group.group_id if self.group else self.sender.user_id,
            session_title=self.group.group_name if self.group else self.sender.nickname
        )

    def get_log_info(self):
        if self.is_group_message():
            return f"[{self.adapter.name} | {self.message_id}] [{self.group.group_name} | {self.sender.nickname}]: {self.message_repr}"
        else:
            return f"[{self.adapter.name} | {self.message_id}] [{self.sender.nickname}]: {self.message_repr}"

    def is_group_message(self) -> bool:
        """judge whether it's a group message"""
        return self.group is not None

    @property
    def is_stopped(self):
        return self._is_stopped

    def stop(self):
        self._is_stopped = True


@dataclass
class KiraCommentEvent:
    platform: str
    adapter_name: str
    commenter_id: str
    commenter_nickname: str
    self_id: str
    timestamp: int
    cmt_id: Union[int, str]
    cmt_content: list
    sub_cmt_id: Union[int, str] = None
    sub_cmt_content: Optional[list] = None
    message_str: Optional[str] = field(default=None, init=False)

    def __post_init__(self):
        pass


@dataclass
class KiraExceptionEvent:
    name: str
    message: str
    source: str = None

    def __post_init__(self):
        pass


class MessageChain:
    def __init__(self, message_list: list[Text, Image, At, Reply, Emoji, Sticker, Record, Notice, File]):
        self.message_list: list = message_list

    def __iter__(self):
        return iter(self.message_list)

    def __len__(self):
        return len(self.message_list)

    def __getitem__(self, index):
        return self.message_list[index]

    def __delitem__(self, index):
        del self.message_list[index]

    def text(self, text: str):
        self.message_list.append(Text(text))
        return self

    def image(self, url: str):
        self.message_list.append(Image(url))
        return self

    def at(self, pid: Union[int, str], nickname: Optional[str]):
        self.message_list.append(At(pid, nickname))
        return self

    def reply(self, message_id):
        if not self.message_list:
            self.message_list.append(Reply(message_id))
        return self

    def emoji(self, emoji_id):
        self.message_list.append(Emoji(emoji_id))
        return self

    def sticker(self, sticker_id):
        self.message_list.append(Sticker(sticker_id))
        return self

    def record(self, bs64):
        self.message_list.append(Record(bs64))
        return self

    def notice(self, notice):
        self.message_list.append(Notice(notice))
        return self

    def poke(self, pid):
        self.message_list.append(Poke(pid))
        return self

from __future__ import annotations

import uuid

from dataclasses import dataclass, field
from enum import Enum
from typing import Union, Optional, Literal

from core.chat.message_elements import (
    BaseMessageElement,
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
from core.prompt_manager import Prompt


class MessageType(Enum):
    GroupMsg = "gm"
    DirectMsg = "dm"
    SystemMsg = "sm"


@dataclass
class KiraIMMessage:
    message_id: str
    self_id: str

    # TODO unify to MessageChain
    chain: Union[list[BaseMessageElement], MessageChain]

    timestamp: int
    sender: User = None
    session: Session = None
    group: Group = None
    is_notice: bool = False
    is_mentioned: Optional[bool] = None
    extra: Optional[dict] = None
    message_str: Optional[str] = field(default=None, init=False)
    message_repr: Optional[str] = field(default=None, init=False)

    def is_group_message(self):
        return self.group is not None


@dataclass
class KiraIMSentResult:
    message_id: Optional[str] = None
    is_notice: bool = False
    ok: bool = True
    err: str = ""


@dataclass
class KiraStepResult:
    message_results: list[KiraIMSentResult]
    raw_output: str


@dataclass
class KiraMessageEvent:
    message_types: list
    timestamp: int
    message: KiraIMMessage
    _process_strategy: Literal["trigger", "buffer", "discard", "flush"] = "discard"
    adapter: AdapterInfo = None
    extra: Optional[dict] = None
    message_str: Optional[str] = field(default=None, init=False)
    message_repr: Optional[str] = field(default=None, init=False)
    _is_stopped: bool = False
    _is_forced: bool = False

    def __post_init__(self):
        self.message_repr = " ".join(ele.repr for ele in self.message.chain)
        self.session = Session(
            adapter_name=self.adapter.name,
            session_type="gm" if self.message.group else "dm",
            session_id=self.message.group.group_id if self.message.group else self.message.sender.user_id,
            session_title=self.message.group.group_name if self.message.group else self.message.sender.nickname
        )

    def get_log_info(self):
        if self.is_group_message():
            return f"[{self.adapter.name} | {self.message.message_id}] [{self.message.group.group_name} | {self.message.sender.nickname}]: {self.message_repr}"
        else:
            return f"[{self.adapter.name} | {self.message.message_id}] [{self.message.sender.nickname}]: {self.message_repr}"

    def is_group_message(self) -> bool:
        """judge whether it's a group message"""
        return self.message.group is not None

    @property
    def is_mentioned(self):
        return self.message.is_mentioned

    @property
    def is_notice(self):
        return self.message.is_notice

    @property
    def is_stopped(self):
        return self._is_stopped

    @property
    def process_strategy(self):
        return self._process_strategy

    def stop(self):
        self._is_stopped = True

    def trigger(self, force: bool = False):
        if self._is_forced:
            return False
        self._process_strategy = "trigger"
        self._is_forced = force
        return True

    def buffer(self, force: bool = False):
        if self._is_forced:
            return False
        self._process_strategy = "buffer"
        self._is_forced = force
        return True

    def flush(self, force: bool = False):
        if self._is_forced:
            return False
        self._process_strategy = "flush"
        self._is_forced = force
        return True

    def discard(self, force: bool = False):
        if self._is_forced:
            return False
        self._process_strategy = "discard"
        self._is_forced = force
        return True


@dataclass
class KiraMessageBatchEvent:
    message_types: list
    timestamp: int

    """event id to uniquely identify a event"""
    event_id: str = None
    adapter: AdapterInfo = None
    session: Session = None

    messages: list[KiraIMMessage] = field(default_factory=list)

    extra: Optional[dict] = None
    message_str: Optional[str] = field(default=None, init=False)

    """Message display text for logging"""
    message_repr: Optional[str] = field(default=None, init=False)

    _is_stopped: bool = False

    def __post_init__(self):
        self.event_id = uuid.uuid4().hex

    def is_group_message(self):
        return self.messages[-1].group is not None

    @property
    def self_id(self):
        return self.messages[-1].self_id

    @property
    def sid(self):
        return self.session.sid

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
    traceback: str = None
    source: str = None

    def __post_init__(self):
        pass


class MessageChain:
    def __init__(self, message_list: list[BaseMessageElement]):
        self.message_list: list = message_list

    def __iter__(self):
        return iter(self.message_list)

    def __len__(self):
        return len(self.message_list)

    def __getitem__(self, index):
        return self.message_list[index]

    def __delitem__(self, index):
        del self.message_list[index]

    def is_empty(self) -> bool:
        return len(self.message_list) == 0

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

    def record(self, record: str):
        self.message_list.append(Record(record=record))
        return self

    def notice(self, notice):
        self.message_list.append(Notice(notice))
        return self

    def poke(self, pid):
        self.message_list.append(Poke(pid))
        return self

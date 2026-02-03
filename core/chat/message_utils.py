from dataclasses import dataclass, field
from typing import Union, Optional, List

from core.chat.message_elements import (
    Text,
    Image,
    At,
    Reply,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke
)


@dataclass
class KiraMessageEvent:
    platform: str
    adapter_name: str
    message_types: list
    user_id: str
    user_nickname: str
    message_id: str
    self_id: str
    content: List
    timestamp: int
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    is_mentioned: Optional[bool] = None
    message_str: Optional[str] = field(default=None, init=False)
    message_repr: Optional[str] = field(default=None, init=False)

    def __post_init__(self):
        self.message_repr = " ".join(ele.repr for ele in self.content)

    def is_group_message(self) -> bool:
        """judge whether it's a group message"""
        return self.group_id is not None


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
class BotDirectMessage(KiraMessageEvent):
    """私聊消息"""

    def __post_init__(self):
        self.group_id = None
        self.group_name = None
        super().__post_init__()


@dataclass
class BotGroupMessage(KiraMessageEvent):
    """群组消息"""

    def __post_init__(self):
        super().__post_init__()


class MessageChain:
    def __init__(self, message_list: list[Text, Image, At, Reply, Emoji, Sticker, Record, Notice]):
        self.message_list: list = message_list

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

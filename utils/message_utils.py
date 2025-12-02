from dataclasses import dataclass, field
from typing import Union, Optional, List, Type


@dataclass
class KiraMessageEvent:
    platform: str
    adapter_name: str
    message_types: List[Type]
    user_id: str
    user_nickname: str
    message_id: str
    self_id: str
    content: List
    timestamp: int
    group_id: Optional[str] = None
    group_name: Optional[str] = None
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
    comment_id: str
    self_id: str
    content: list
    timestamp: int
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


class MessageType:
    class Text:
        def __init__(self, text: str):
            self.text: str = text

        @property
        def repr(self):
            return self.text

    class Image:
        def __init__(self, url: str):
            self.url: str = url

        @property
        def repr(self):
            return "[Image]"

    class At:
        def __init__(self, pid: Union[int, str], nickname: Optional[str] = None):
            """set pid to 'all' to at all group members"""
            self.pid: str = str(pid)
            self.nickname: str = nickname

        @property
        def repr(self):
            if self.nickname:
                return f"[At {self.nickname}({self.pid})]"
            else:
                return f"[At {self.pid}]"

    class Reply:
        def __init__(self, message_id: Union[int, str], message_content: Optional[str] = None):
            self.message_id: str = str(message_id)
            self.message_content: str = message_content

        @property
        def repr(self):
            return f"[Reply {self.message_id}]"

    class Emoji:
        def __init__(self, emoji_id: Union[int, str]):
            self.emoji_id: str = str(emoji_id)

        @property
        def repr(self):
            return f"[Emoji {self.emoji_id}]"

    class Sticker:
        def __init__(self, sticker_id: Union[int, str], sticker_bs64: str):
            self.sticker_id: str = str(sticker_id)
            self.sticker_bs64: str = sticker_bs64

        @property
        def repr(self):
            return f"[Sticker {self.sticker_id}]"

    class Record:
        def __init__(self, bs64: str):
            self.bs64: str = bs64

        @property
        def repr(self):
            return f"[Record]"

    class Notice:
        def __init__(self, text: str):
            self.text = text

        @property
        def repr(self):
            return f"[Notice]"

    class Poke:
        def __init__(self, pid: Union[int, str]):
            self.pid = str(pid)

        @property
        def repr(self):
            return f"[Poke]"


class MessageSending:
    def __init__(self, message_list: list[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]):
        self.message_list: list = message_list

    def text(self, text: str):
        self.message_list.append(MessageType.Text(text))
        return self

    def image(self, url: str):
        self.message_list.append(MessageType.Image(url))
        return self

    def at(self, pid: Union[int, str], nickname: Optional[str]):
        self.message_list.append(MessageType.At(pid, nickname))
        return self

    def reply(self, message_id):
        if not self.message_list:
            self.message_list.append(MessageType.Reply(message_id))
        return self

    def emoji(self, emoji_id):
        self.message_list.append(MessageType.Emoji(emoji_id))
        return self

    def sticker(self, sticker_id):
        self.message_list.append(MessageType.Sticker(sticker_id))
        return self

    def record(self, bs64):
        self.message_list.append(MessageType.Record(bs64))
        return self

    def notice(self, notice):
        self.message_list.append(MessageType.Notice(notice))
        return self

    def poke(self, pid):
        self.message_list.append(MessageType.Poke(pid))
        return self

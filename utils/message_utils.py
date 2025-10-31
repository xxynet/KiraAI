from typing import Union, Optional


class BotPrivateMessage:
    def __init__(self, platform: str, adapter_name: str, message_types: list, user_id: str, user_nickname: str, message_id: str, self_id: str, content: list, timestamp: int):
        self.platform = platform
        self.adapter_name = adapter_name
        self.message_types = message_types
        self.user_id = user_id
        self.user_nickname = user_nickname
        self.message_id = message_id
        self.self_id = self_id
        self.content = content
        self.message_str = None
        self.timestamp = timestamp

    def __repr__(self):
        return f"<Message from={self.platform} user={self.user_id} content={self.content}>"


class BotGroupMessage:
    def __init__(self, platform: str, adapter_name: str, message_types: list, group_id: str, group_name: str, user_id: str, user_nickname: str, message_id: str, self_id: str, content: list, timestamp: int):
        self.platform = platform
        self.adapter_name = adapter_name
        self.message_types = message_types
        self.group_id = group_id
        self.group_name = group_name
        self.user_id = user_id
        self.user_nickname = user_nickname
        self.message_id = message_id
        self.self_id = self_id
        self.content = content
        self.message_str = None
        self.timestamp = timestamp

    def __repr__(self):
        return f"<GroupMessage from={self.platform} group={self.group_id} user={self.user_id} content={self.content}>"


class MessageType:
    class Text:
        def __init__(self, text: str):
            self.text: str = text

    class Image:
        def __init__(self, url: str):
            self.url: str = url

    class At:
        def __init__(self, pid: Union[int, str], nickname: Optional[str] = None):
            """set pid to 'all' to at all group members"""
            self.pid: str = str(pid)
            self.nickname: str = nickname

    class Reply:
        def __init__(self, message_id: Union[int, str], message_content: Optional[str] = None):
            self.message_id: str = str(message_id)
            self.message_content: str = message_content

    class Emoji:
        def __init__(self, emoji_id: Union[int, str]):
            self.emoji_id: str = str(emoji_id)

    class Sticker:
        def __init__(self, sticker_id: Union[int, str], sticker_bs64: str):
            self.sticker_id: str = str(sticker_id)
            self.sticker_bs64: str = sticker_bs64

    class Record:
        def __init__(self, bs64: str):
            self.bs64: str = bs64

    class Notice:
        def __init__(self, text: str):
            self.text = text

    class Poke:
        def __init__(self, pid: Union[int, str]):
            self.pid = str(pid)


class MessageSending:
    def __init__(self, message_list: list[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]):
        self.message_list: list = message_list

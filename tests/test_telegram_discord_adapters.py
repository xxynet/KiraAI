import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from telegram import Chat, Message, MessageEntity, Update, User as TelegramUser

from core.adapter import AdapterContext, BaseAdapter
from core.adapter.adapter_info import AdapterInfo
from core.adapter.adapter_registry import AdapterManager
from core.adapter.capabilities import IMCapability
from core.adapter.src.telegram.telegram import TelegramAdapter
from core.adapter.src.discord.discord import DiscordAdapter
from core.chat import KiraIMSentResult, MessageChain
from core.chat.message_elements import At, Emoji, File, Image, Record, Reply, Sticker, Text, Video
from core.plugin.plugin_context import PluginContext
from tests.test_adapter_routing import processor_for


class FakeApplication:
    def __init__(self):
        self.running = False
        self.handlers = []
        self.bot = NS(id=99, username="KiraBot", full_name="Kira", get_file=AsyncMock())
        for method in ("send_message", "send_photo", "send_voice", "send_sticker", "send_document", "send_video"):
            setattr(self.bot, method, AsyncMock(return_value=NS(message_id=501)))
        self.updater = NS(running=False, start_polling=AsyncMock(side_effect=self._poll), stop=AsyncMock(side_effect=self._unpoll))
        self.initialize = AsyncMock()
        self.start = AsyncMock(side_effect=self._start)
        self.stop = AsyncMock(side_effect=self._stop)
        self.shutdown = AsyncMock()

    def add_handler(self, handler):
        self.handlers.append(handler)

    async def _start(self):
        self.running = True

    async def _stop(self):
        self.running = False

    async def _poll(self, **kwargs):
        self.updater.running = True

    async def _unpoll(self):
        self.updater.running = False


class FakeDiscordBot:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.user = NS(id=99)
        self.events = {}
        self.commands = {}
        self.closed = False
        self.latency = 0.123
        self.pending_application_commands = []
        self.start = AsyncMock(side_effect=self._start)
        self.close = AsyncMock(side_effect=self._close)
        self.channel = NS(send=AsyncMock(return_value=NS(id=501)), fetch_message=AsyncMock(return_value=NS(id=10)))
        self.get_channel = Mock(return_value=self.channel)
        self.fetch_channel = AsyncMock(return_value=self.channel)
        self.dm_user = NS(dm_channel=self.channel, create_dm=AsyncMock(return_value=self.channel))
        self.get_user = Mock(return_value=self.dm_user)
        self.fetch_user = AsyncMock(return_value=self.dm_user)

    def event(self, callback):
        self.events[callback.__name__] = callback
        return callback

    def slash_command(self, **kwargs):
        def register(callback):
            self.commands[kwargs["name"]] = (callback, kwargs)
            return callback
        return register

    def is_closed(self):
        return self.closed

    async def _start(self, token):
        await asyncio.Event().wait()

    async def _close(self):
        self.closed = True


@pytest.fixture
def adapter_factory(monkeypatch):
    apps = []
    bots = []

    def builder_factory():
        app = FakeApplication()
        apps.append(app)
        builder = Mock()
        for method in ("token", "base_url", "base_file_url", "get_updates_connection_pool_size", "get_updates_pool_timeout"):
            getattr(builder, method).return_value = builder
        builder.build.return_value = app
        return builder

    def bot_factory(**kwargs):
        bot = FakeDiscordBot(**kwargs)
        bots.append(bot)
        return bot

    monkeypatch.setattr("core.adapter.src.telegram.telegram.ApplicationBuilder", builder_factory)
    monkeypatch.setattr("core.adapter.src.discord.discord.discord.Bot", bot_factory)

    def create(platform, config=None, name=None):
        info = AdapterInfo(
            adapter_id=name or f"{platform.lower()}-test",
            name=name or f"{platform.lower()}-test", enabled=True, platform=platform,
            config={"bot_token": "test-token", "bot_pid": "KiraBot", **(config or {})},
        )
        cls = TelegramAdapter if platform == "Telegram" else DiscordAdapter
        adapter = cls(AdapterContext(info, asyncio.Queue()))
        adapter.logger = Mock()
        return adapter

    return create


def tg_update(group=False, **kwargs):
    user = TelegramUser(id=123, first_name="Tester", is_bot=False)
    chat = Chat(id=-456 if group else 123, type="supergroup" if group else "private", title="Test group" if group else None)
    message = Message(message_id=42, date=datetime(2026, 10, 4, tzinfo=timezone.utc), chat=chat, from_user=user, **kwargs)
    return Update(update_id=1, message=message)


def dc_message(adapter, group=False, **kwargs):
    guild = NS(me=NS(roles=[NS(id=8)]), get_role=lambda rid: NS(name="Bot role"), get_member=lambda uid: NS(display_name="Tester")) if group else None
    fields = dict(
        id=42, author=NS(id=123, display_name="Tester"), guild=guild,
        channel=NS(id=456, name="thread-or-channel"), created_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        content="hello", mentions=[], role_mentions=[], mention_everyone=False, reference=None, attachments=[], stickers=[],
    )
    fields.update(kwargs)
    return Mock(spec=discord.Message, **fields)


@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
def test_registers_one_owned_im_capability(adapter_factory, platform):
    adapter = adapter_factory(platform)
    assert isinstance(adapter, BaseAdapter)
    assert adapter.get_capability(IMCapability) is adapter.im
    assert adapter.get_capabilities() == {IMCapability: adapter.im}
    assert adapter.im.adapter is adapter
    assert adapter.get_client() is (adapter.app if platform == "Telegram" else adapter.bot)
    assert not hasattr(adapter, "group_list")
    assert not hasattr(adapter, "user_list")
    assert not hasattr(adapter, "permission_mode")
    with pytest.raises(ValueError):
        adapter.register_capability(IMCapability, type(adapter.im)(adapter))


@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("scope,target", [("direct", "user"), ("group", "group")])
@pytest.mark.parametrize("config,allowed,denied", [
    ({}, [], [123, "123", None]),
    ({"permission_mode": "allow_list", "allow": [123]}, [123, "123"], [456, None]),
    ({"permission_mode": "allow_list", "allow": ["123"]}, [123, "123"], [456, None]),
    ({"permission_mode": "allow_list", "allow": "123"}, [], [123, None]),
    ({"permission_mode": "deny_list", "deny": [123]}, [456, "456"], [123, "123", None]),
    ({"permission_mode": "deny_list", "deny": "123"}, [123], [None]),
    ({"permission_mode": "deny_list"}, [123], [None]),
    ({"permission_mode": "invalid", "allow": [123]}, [], [123, None]),
])
def test_platform_permission_config_preserves_modes_and_normalizes_ids(adapter_factory, platform, scope, target, config, allowed, denied):
    config = dict(config)
    for suffix, alias in (("allow_list", "allow"), ("deny_list", "deny")):
        if alias in config:
            config[f"{target}_{suffix}"] = config.pop(alias)
    adapter = adapter_factory(platform, config)
    permission = f"im.{scope}.receive"
    for target_id in allowed:
        assert adapter.im.is_allowed(target_id, permission=permission)
    for target_id in denied:
        assert not adapter.im.is_allowed(target_id, permission=permission)
    assert not adapter.im.is_allowed(123, permission="im.other.receive")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("group", [False, True])
async def test_incoming_messages_keep_metadata_and_native_session_targets(adapter_factory, platform, group):
    adapter = adapter_factory(platform, {"permission_mode": "deny_list"})
    if platform == "Telegram":
        await adapter.im._on_message(tg_update(group, text="hello"), None)
        target = "-456" if group else "123"
    else:
        await adapter.im._handle_message(dc_message(adapter, group))
        target = "456" if group else "123"
    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == f"{adapter.info.name}:{'gm' if group else 'dm'}:{target}"
    assert event.message.sender.user_id == "123"
    assert event.message.message_id == "42"
    assert event.message.chain[0].text == "hello"
    assert event.message_types == adapter.message_types
    assert event.adapter is adapter.info
    assert not hasattr(event, "capability_name")
    assert event.message.is_mentioned is (not group)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("group", [False, True])
async def test_rejected_incoming_messages_do_not_convert_or_publish(adapter_factory, platform, group):
    adapter = adapter_factory(platform)
    adapter.im._process_incoming_message = AsyncMock()
    if platform == "Telegram":
        await adapter.im._on_message(tg_update(group, text="hello"), None)
    else:
        await adapter.im._handle_message(dc_message(adapter, group))
    adapter.im._process_incoming_message.assert_not_awaited()
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("group", [False, True])
async def test_core_and_adapter_send_through_registered_im(adapter_factory, platform, group):
    adapter = adapter_factory(platform)
    method = "send_group_message" if group else "send_direct_message"
    send = AsyncMock(return_value=KiraIMSentResult("501"))
    setattr(adapter.im, method, send)
    chain = MessageChain([Text("reply")])
    target = "-456" if platform == "Telegram" and group else "123"
    await processor_for(adapter).send_message_chain(f"{adapter.info.name}:{'gm' if group else 'dm'}:{target}", chain)
    send.assert_awaited_once_with(target, chain)
    send.reset_mock()
    assert (await getattr(adapter, method)(target, chain)).message_id == "501"
    send.assert_awaited_once_with(target, chain)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("group", [False, True])
async def test_plugin_notices_use_adapter_metadata_and_session_format(adapter_factory, platform, group):
    adapter = adapter_factory(platform)
    ctx = PluginContext.__new__(PluginContext)
    ctx.adapter_mgr = NS(get_adapter=lambda name: adapter)
    ctx.event_bus = NS(publish=AsyncMock())
    sid = f"{adapter.info.name}:{'gm' if group else 'dm'}:123"
    await ctx.publish_notice(sid, MessageChain([Text("notice")]))
    event = ctx.event_bus.publish.await_args.args[0]
    assert event.session.sid == sid
    assert event.message.is_notice
    assert event.message_types == adapter.message_types
    assert event.message_types is not adapter.message_types


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_manager_constructs_and_stops_migrated_adapter_with_context(adapter_factory, monkeypatch, platform):
    template = adapter_factory(platform)
    monkeypatch.setitem(AdapterManager._registry, platform, type(template))
    manager = AdapterManager.__new__(AdapterManager)
    manager.event_queue = asyncio.Queue()
    manager._adapters = {}
    manager._adapter_tasks = {}
    await manager.register_adapter(template.info)
    adapter = manager.get_adapter(template.info.name)
    assert adapter.ctx.event_queue is manager.event_queue
    assert adapter.ctx.info is template.info
    await manager.stop_adapter(template.info.name)
    assert not manager._adapters
    assert not manager._adapter_tasks
    if platform == "Discord":
        assert adapter._bot_task.done()
    else:
        adapter.app.shutdown.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_repeated_start_stop_restart_and_multiple_accounts(adapter_factory, platform):
    first = adapter_factory(platform, {"user_allow_list": [123]}, "first")
    second = adapter_factory(platform, {"user_allow_list": [456]}, "second")
    assert first.im is not second.im
    assert first.message_sender is not second.message_sender
    assert first.im.is_allowed(123, permission="im.direct.receive")
    assert not second.im.is_allowed(123, permission="im.direct.receive")
    await asyncio.gather(first.start(), first.start(), second.start())
    await asyncio.sleep(0)
    old_client = first.get_client()
    if platform == "Telegram":
        first.app.initialize.assert_awaited_once()
        assert len(first.app.handlers) == 3
        first.emoji_dict["test"] = "only first"
        assert "test" not in second.emoji_dict
    else:
        first.bot.start.assert_awaited_once()
        assert set(first.bot.commands) == {"ping", "help"}
    await asyncio.gather(first.stop(), first.stop())
    if platform == "Telegram":
        assert not first.app.running
        assert second.app.running
    else:
        assert first.bot.closed
        assert not second.bot.closed
    await first.start()
    await asyncio.sleep(0)
    if platform == "Telegram":
        assert first.app.running
        assert len(first.app.handlers) == 3
        assert first.app.initialize.await_count == 2
    else:
        assert first.bot is not old_client
        assert set(first.bot.commands) == {"ping", "help"}
        first.im._handle_message = AsyncMock()
        await old_client.events["on_message"](dc_message(first))
        first.im._handle_message.assert_not_awaited()
    await asyncio.gather(first.stop(), second.stop())
    assert not first._message_tasks and not second._message_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_stop_cancels_own_inflight_callback_and_rejects_late_messages(adapter_factory, platform):
    adapter = adapter_factory(platform, {"permission_mode": "deny_list"})
    entered = asyncio.Event()
    finished = asyncio.Event()

    async def blocked_conversion(message):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    adapter.im._process_incoming_message = blocked_conversion
    await adapter.start()
    if platform == "Telegram":
        receive = lambda: adapter._on_message(tg_update(text="hello"), None)
    else:
        receive = lambda: adapter.bot.events["on_message"](dc_message(adapter))
    task = asyncio.create_task(receive())
    await entered.wait()
    await adapter.stop()
    assert task.cancelled()
    assert finished.is_set()
    assert adapter.ctx.event_queue.empty()
    assert not adapter._message_tasks
    await receive()
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("using_caption", [False, True])
async def test_telegram_utf16_mentions_and_caption_survive_conversion(adapter_factory, using_caption):
    adapter = adapter_factory("Telegram", {"permission_mode": "deny_list"})
    entity = MessageEntity(type="mention", offset=3, length=8)
    fields = {"caption": "😀 @KiraBot hello", "caption_entities": [entity]} if using_caption else {"text": "😀 @KiraBot hello", "entities": [entity]}
    await adapter.im._on_message(tg_update(True, **fields), None)
    event = adapter.ctx.event_queue.get_nowait()
    assert event.message.is_mentioned
    assert [type(ele) for ele in event.message.chain] == [Text, At, Text]
    assert event.message.chain[0].text == "😀 "
    assert event.message.chain[1].pid == "KiraBot"
    assert event.message.chain[1].nickname == "Kira"
    assert event.message.chain[2].text == " hello"


@pytest.mark.asyncio
async def test_telegram_reply_and_text_mention_detection(adapter_factory):
    adapter = adapter_factory("Telegram", {"permission_mode": "deny_list"})
    bot_user = TelegramUser(id=99, first_name="Kira", is_bot=True)
    reply = Message(message_id=10, date=datetime.now(timezone.utc), chat=Chat(-456, "supergroup"), from_user=bot_user, text="previous")
    await adapter.im._on_message(tg_update(True, text="reply", reply_to_message=reply), None)
    event = adapter.ctx.event_queue.get_nowait()
    assert event.message.is_mentioned
    assert event.message.chain[0].message_id == "10"
    entity = MessageEntity(type="text_mention", offset=0, length=4, user=bot_user)
    await adapter.im._on_message(tg_update(True, text="Kira hello", entities=[entity]), None)
    assert adapter.ctx.event_queue.get_nowait().message.is_mentioned


@pytest.mark.asyncio
async def test_telegram_ignores_missing_message_or_sender(adapter_factory):
    adapter = adapter_factory("Telegram", {"permission_mode": "deny_list"})
    await adapter.im._on_message(Update(1), None)
    await adapter.im._on_message(NS(effective_message=NS(from_user=None)), None)
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected", [("photo", Image), ("voice", Record), ("audio", Record), ("document", File), ("video", Video), ("sticker", Sticker)])
async def test_telegram_incoming_media(adapter_factory, monkeypatch, kind, expected):
    adapter = adapter_factory("Telegram")
    adapter.app.bot.get_file.return_value = NS(file_path="https://example.com/media")
    monkeypatch.setattr("core.adapter.src.telegram.im.get_file_content", AsyncMock(return_value=b"media"))
    message = NS(reply_to_message=None, text=None, caption=None, photo=[], voice=None, audio=None, document=None, video=None, sticker=None)
    media = NS(file_id="media-id", file_name="sample", file_size=5, mime_type="application/octet-stream", is_animated=False, is_video=False, emoji="🙂")
    setattr(message, kind, [media] if kind == "photo" else media)
    chain = await adapter.im._process_incoming_message(message)
    assert isinstance(chain[0], expected)
    adapter.app.bot.get_file.assert_awaited_once_with("media-id")
    if expected == Sticker:
        assert chain[0].mime == "image/webp"
    elif expected in (File, Video):
        assert chain[0].name == "sample"
        assert chain[0].size == "5"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,target", [("send_group_message", "-456"), ("send_direct_message", "123")])
async def test_telegram_sends_merged_html_reply_mentions_and_emoji(adapter_factory, method, target):
    adapter = adapter_factory("Telegram")
    adapter.emoji_dict = {"1": "🙂"}
    chain = MessageChain([Reply("10"), Text("<hello> & "), At("123", "Test & Name"), At("username"), At("all"), Emoji("1")])
    result = await getattr(adapter.im, method)(target, message=chain)
    assert result.ok and result.message_id == "501"
    kwargs = adapter.app.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == int(target)
    assert kwargs["reply_to_message_id"] == 10
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["text"] == '&lt;hello&gt; &amp; <a href="tg://user?id=123">@Test &amp; Name</a>@username@all🙂'


@pytest.mark.asyncio
@pytest.mark.parametrize("element,method,field", [(Image, "send_photo", "photo"), (Record, "send_voice", "voice"), (Sticker, "send_sticker", "sticker"), (File, "send_document", "document"), (Video, "send_video", "video")])
async def test_telegram_outgoing_media_preserves_order_and_reply(adapter_factory, tmp_path, element, method, field):
    adapter = adapter_factory("Telegram")
    path = tmp_path / "media.bin"
    path.write_bytes(b"media")
    ele = element(str(path)) if element != Sticker else Sticker(sticker="bWVkaWE=")
    ele.to_base64 = AsyncMock(return_value="bWVkaWE=")
    ele.to_path = AsyncMock(return_value=str(path))
    result = await adapter.im.send_direct_message(123, MessageChain([Reply("10"), ele, Text("after")]))
    send = getattr(adapter.app.bot, method)
    assert result.ok
    assert send.await_args.kwargs[field] == b"media"
    assert send.await_args.kwargs["reply_to_message_id"] == 10
    assert "reply_to_message_id" not in adapter.app.bot.send_message.await_args.kwargs


@pytest.mark.asyncio
async def test_telegram_start_failure_cleans_started_components(adapter_factory):
    adapter = adapter_factory("Telegram")
    adapter.app.updater.start_polling.side_effect = RuntimeError("sensitive-token")
    await adapter.start()
    adapter.app.stop.assert_awaited_once()
    adapter.app.shutdown.assert_awaited_once()
    assert not adapter._accepting_messages
    assert not adapter.app.running


@pytest.mark.asyncio
@pytest.mark.parametrize("mention", ["user", "role", "everyone", "reply"])
async def test_discord_group_mentions_and_reply_detection(adapter_factory, mention):
    adapter = adapter_factory("Discord", {"permission_mode": "deny_list"})
    fields = {}
    if mention == "user":
        fields["mentions"] = [adapter.bot.user]
    elif mention == "role":
        fields["role_mentions"] = [NS(id=8)]
    elif mention == "everyone":
        fields["mention_everyone"] = True
    else:
        fields["reference"] = NS(resolved=Mock(spec=discord.Message, id=10, author=adapter.bot.user, content="previous"))
    await adapter.im._handle_message(dc_message(adapter, True, **fields))
    event = adapter.ctx.event_queue.get_nowait()
    assert event.message.is_mentioned
    if mention == "reply":
        assert event.message.chain[0].message_id == "10"


@pytest.mark.asyncio
async def test_discord_ignores_self_and_unready_client(adapter_factory):
    adapter = adapter_factory("Discord", {"permission_mode": "deny_list"})
    await adapter.im._handle_message(dc_message(adapter, author=adapter.bot.user))
    adapter.bot.user = None
    await adapter.im._handle_message(dc_message(adapter))
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_discord_duplicate_user_and_role_mentions_preserve_order(adapter_factory):
    adapter = adapter_factory("Discord")
    chain = await adapter.im._process_incoming_message(dc_message(adapter, True, content="a<@123>b<@!123>c<@&8>d"))
    assert [type(ele) for ele in chain] == [Text, At, Text, At, Text, At, Text]
    assert [ele.pid for ele in chain if isinstance(ele, At)] == ["123", "123", "8"]
    assert chain[5].nickname == "@Bot role"


@pytest.mark.asyncio
@pytest.mark.parametrize("mime,expected", [("image/png", Image), ("video/mp4", Video), ("audio/ogg", Record), ("application/pdf", File), ("", File)])
async def test_discord_incoming_attachments(adapter_factory, monkeypatch, mime, expected):
    adapter = adapter_factory("Discord")
    monkeypatch.setattr("core.utils.network.get_file_content", AsyncMock(return_value=b"media"))
    att = NS(content_type=mime, width=400, height=400, url="https://example.com/media", filename="sample", size=5)
    chain = await adapter.im._process_incoming_message(dc_message(adapter, content="", attachments=[att]))
    assert isinstance(chain[0], expected)
    if expected in (File, Video):
        assert chain[0].name == "sample" and chain[0].size == "5"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["send_group_message", "send_direct_message"])
async def test_discord_sends_merged_text_mentions_emoji_and_reply(adapter_factory, method):
    adapter = adapter_factory("Discord")
    chain = MessageChain([Reply("10"), Text("hello "), At("123"), At("all"), Emoji("9", "wave"), Emoji("🙂")])
    result = await getattr(adapter.im, method)("456", message=chain)
    assert result.ok and result.message_id == "501"
    kwargs = adapter.bot.channel.send.await_args.kwargs
    assert kwargs["content"] == "hello <@123>@everyone<:wave:9>🙂"
    assert kwargs["reference"].id == 10
    adapter.bot.channel.fetch_message.assert_awaited_once_with(10)


@pytest.mark.asyncio
@pytest.mark.parametrize("element,filename", [(Image, "image.png"), (Record, "voice.mp3"), (Sticker, "sticker.gif"), (File, "file"), (Video, "video.mp4")])
async def test_discord_outgoing_media_preserves_attachment_and_reply(adapter_factory, tmp_path, element, filename):
    adapter = adapter_factory("Discord")
    path = tmp_path / "media.bin"
    path.write_bytes(b"media")
    ele = element(str(path)) if element != Sticker else Sticker(sticker="bWVkaWE=", mime="image/gif")
    ele.to_path = AsyncMock(return_value=str(path))
    ele.to_base64 = AsyncMock(return_value="bWVkaWE=")
    try:
        result = await adapter.im.send_group_message(456, MessageChain([Reply("10"), ele, Text("after")]))
        assert result.ok
        calls = adapter.bot.channel.send.await_args_list
        assert calls[0].kwargs["file"].filename == filename
        assert calls[0].kwargs["file"].fp.read() == b"media"
        assert calls[0].kwargs["reference"].id == 10
        assert "reference" not in calls[1].kwargs
    finally:
        for call in adapter.bot.channel.send.await_args_list:
            if "file" in call.kwargs:
                call.kwargs["file"].close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_discord_channel_fetch_and_dm_creation(adapter_factory, cached):
    adapter = adapter_factory("Discord")
    if not cached:
        adapter.bot.get_channel.return_value = None
        adapter.bot.get_user.return_value = None
    adapter.bot.dm_user.dm_channel = None
    assert (await adapter.im.send_group_message(456, MessageChain([Text("group")]))).ok
    assert (await adapter.im.send_direct_message(123, MessageChain([Text("dm")]))).ok
    adapter.bot.dm_user.create_dm.assert_awaited_once()
    assert adapter.bot.fetch_channel.await_count == (0 if cached else 1)
    assert adapter.bot.fetch_user.await_count == (0 if cached else 1)


@pytest.mark.asyncio
async def test_platform_native_commands_are_bound_to_their_own_account(adapter_factory):
    tg = adapter_factory("Telegram")
    message = NS(reply_text=AsyncMock())
    await tg.im._cmd_start(NS(effective_message=message), None)
    await tg.im._cmd_help(NS(effective_message=message), None)
    assert message.reply_text.await_args_list[0].args == ("Hi, I'm online.",)
    assert message.reply_text.await_args_list[1].args == ("Help: just talk to me.",)
    dc = adapter_factory("Discord", {"slash_guild_ids": [123], "auto_sync_commands": False})
    ctx = NS(respond=AsyncMock())
    await dc.bot.commands["ping"][0](ctx)
    assert ctx.respond.await_args.args == ("🏓 Pong! Latency: 123ms",)
    assert ctx.respond.await_args.kwargs["ephemeral"]
    await dc.bot.commands["help"][0](ctx)
    assert ctx.respond.await_args.kwargs["embed"].title == "KiraAI Help"
    assert dc.bot.commands["ping"][1]["guild_ids"] == [123]
    assert not dc.bot.options["auto_sync_commands"]
    assert dc.bot.options["intents"].members


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
@pytest.mark.parametrize("method", ["send_group_message", "send_direct_message"])
async def test_failed_sends_do_not_expose_exception_payloads(adapter_factory, platform, method):
    adapter = adapter_factory(platform)
    helper = "_send_message_to_chat" if platform == "Telegram" else "_send_message_to_channel"
    setattr(adapter.im, helper, AsyncMock(side_effect=RuntimeError("secret-token and conversation")))
    result = await getattr(adapter.im, method)(123, MessageChain([Text("hello")]))
    assert not result.ok
    assert "RuntimeError" in result.err
    assert "secret-token" not in result.err and "conversation" not in result.err


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("enabled,targets,expected", [
    (False, [], False),
    (True, [], True),
    (True, ["gm:456", "dm:123"], True),
    (True, ["gm:999", "dm:999"], False),
    (True, ["dm:456", "gm:123"], False),
])
async def test_discord_debug_logging_preserves_raw_message_and_target_filter(adapter_factory, group, enabled, targets, expected):
    adapter = adapter_factory("Discord", {
        "permission_mode": "deny_list", "debug_mode": enabled, "debug_mode_list": targets,
    })
    message = dc_message(adapter, group)
    await adapter.im._handle_message(message)
    if expected:
        prefix = "Raw message" if group else "Raw DM"
        adapter.logger.debug.assert_called_once_with(f"{prefix}: {message}")
    else:
        adapter.logger.debug.assert_not_called()


@pytest.mark.asyncio
async def test_discord_task_failure_is_observed_and_records_error(adapter_factory):
    adapter = adapter_factory("Discord")
    adapter.bot.start.side_effect = RuntimeError("secret-token")
    await adapter.start()
    with pytest.raises(RuntimeError):
        await adapter._bot_task
    assert isinstance(adapter._last_error, RuntimeError)
    assert not adapter._accepting_messages
    assert "secret-token" not in repr(adapter.logger.mock_calls)
    await adapter.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_missing_credentials_do_not_start_clients(adapter_factory, platform):
    adapter = adapter_factory(platform, {"bot_token": ""})
    await adapter.start()
    if platform == "Telegram":
        adapter.app.initialize.assert_not_awaited()
    else:
        assert adapter._bot_task is None
        adapter.bot.start.assert_not_awaited()
    assert not adapter._accepting_messages
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_cancellation_during_start_cleans_initialized_client(adapter_factory):
    adapter = adapter_factory("Telegram")
    entered = asyncio.Event()

    async def initialize():
        entered.set()
        await asyncio.Event().wait()

    adapter.app.initialize.side_effect = initialize
    task = asyncio.create_task(adapter.start())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    adapter.app.shutdown.assert_awaited_once()
    assert not adapter._accepting_messages


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_cancelling_stop_waiter_does_not_cancel_other_account(adapter_factory, platform):
    first = adapter_factory(platform, name="first")
    second = adapter_factory(platform, name="second")
    await asyncio.gather(first.start(), second.start())
    entered = asyncio.Event()

    async def close():
        entered.set()
        await asyncio.Event().wait()

    if platform == "Telegram":
        first.app.updater.stop.side_effect = close
    else:
        first.bot.close.side_effect = close
    task = asyncio.create_task(first.stop())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert second._accepting_messages
    if platform == "Telegram":
        assert second.app.running
        first.app.updater.stop.side_effect = first.app._unpoll
    else:
        assert not second.bot.closed
        first.bot.close.side_effect = first.bot._close
    await asyncio.gather(first.stop(), second.stop())


@pytest.mark.asyncio
async def test_discord_missing_user_id_is_rejected_before_string_conversion(adapter_factory):
    adapter = adapter_factory("Discord", {"permission_mode": "deny_list"})
    await adapter.im._handle_message(dc_message(adapter, author=NS(id=None)))
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_discord_attachment_retry_rewinds_memory_stream():
    from core.adapter.src.discord.im import MessageSender
    import io

    sender = MessageSender(max_retries=1, retry_delay=0)
    received = []

    async def send(**kwargs):
        received.append(kwargs["file"].fp.read())
        if len(received) == 1:
            kwargs["file"].close()
            raise RuntimeError("retry")
        return NS(id=501)

    attachment = discord.File(io.BytesIO(b"media"), filename="media.bin")
    try:
        result = await sender.send_with_retry(send, file=attachment)
        assert result.id == 501
        assert received == [b"media", b"media"]
    finally:
        attachment.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["Telegram", "Discord"])
async def test_sender_cancellation_does_not_retry(platform):
    if platform == "Telegram":
        from core.adapter.src.telegram.im import MessageSender
    else:
        from core.adapter.src.discord.im import MessageSender
    sender = MessageSender(retry_delay=0)
    send = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await sender.send_with_retry(send)
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_stop_quiesces_gateway_request_before_closing_session(adapter_factory):
    adapter = adapter_factory("Discord")
    session_closed = asyncio.Event()
    request_started = asyncio.Event()
    request_finished = asyncio.Event()
    events = []

    async def gateway_request():
        request_started.set()
        try:
            await session_closed.wait()
            raise RuntimeError("Session is closed")
        finally:
            request_finished.set()
            events.append("request-finished")

    async def start(token):
        await asyncio.wait_for(gateway_request(), timeout=60)

    async def close():
        session_closed.set()
        events.append("session-closed")
        await asyncio.sleep(0)
        adapter.bot.closed = True

    adapter.bot.start.side_effect = start
    adapter.bot.close.side_effect = close
    await adapter.start()
    await request_started.wait()
    await adapter.stop()
    assert events == ["request-finished", "session-closed"]
    assert request_finished.is_set()
    assert adapter._bot_task.done()
    assert adapter._last_error is None
    adapter.logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_discord_stop_collects_runner_error_that_arrives_during_cancellation(adapter_factory):
    adapter = adapter_factory("Discord")
    started = asyncio.Event()

    async def start(token):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("gateway failure during cancellation")

    adapter.bot.start.side_effect = start
    await adapter.start()
    await started.wait()
    await adapter.stop()
    assert adapter._bot_task.done()
    assert isinstance(adapter._last_error, RuntimeError)
    adapter.logger.error.assert_called_once_with("Discord bot error (%s)", "RuntimeError")
    adapter.bot.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_stop_propagates_client_close_failure_after_runner_exits(adapter_factory):
    adapter = adapter_factory("Discord")
    await adapter.start()
    await asyncio.sleep(0)
    adapter.bot.close.side_effect = RuntimeError("close failure")
    with pytest.raises(RuntimeError, match="close failure"):
        await adapter.stop()
    assert adapter._bot_task.done()
    adapter.bot.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_stop", [False, True])
async def test_discord_stop_quiesces_runner_even_if_callback_cleanup_is_interrupted(adapter_factory, cancel_stop):
    adapter = adapter_factory("Discord")
    runner_started = asyncio.Event()
    cleanup_entered = asyncio.Event()

    async def start(token):
        runner_started.set()
        await asyncio.Event().wait()

    async def cleanup():
        cleanup_entered.set()
        if cancel_stop:
            await asyncio.Event().wait()
        raise RuntimeError("callback cleanup failed")

    async def close():
        assert adapter._bot_task.done()
        adapter.bot.closed = True

    adapter.bot.start.side_effect = start
    adapter.bot.close.side_effect = close
    adapter._cancel_message_tasks = cleanup
    await adapter.start()
    await runner_started.wait()
    task = asyncio.create_task(adapter.stop())
    await cleanup_entered.wait()
    if cancel_stop:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="callback cleanup failed"):
            await task
    assert adapter._bot_task.done()
    assert adapter.bot.closed
    adapter.bot.close.assert_awaited_once()

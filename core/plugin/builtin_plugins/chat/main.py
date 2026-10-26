import asyncio
import random

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent
from core.provider import LLMRequest
from core.adapter.access import ListAccessPolicy
from core.chat.message_elements import Text


class DefaultChatPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.session_events: dict[str, asyncio.Event] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        self._terminating = False

    @property
    def debounce_interval(self) -> float:
        return float(self.ctx.config.get("bot_config", {}).get("bot", {}).get("max_message_interval", 1.5))

    @property
    def max_buffer_messages(self) -> int:
        return int(self.ctx.config.get("bot_config", {}).get("bot", {}).get("max_buffer_messages", 3))

    @property
    def max_unmentioned_messages(self) -> int:
        return int(self.plugin_cfg.get("max_unmentioned_messages", 5))

    @property
    def receive_unmentioned(self) -> bool:
        return self.plugin_cfg.get("receive_unmentioned", True)

    @property
    def group_chat_prompt(self) -> str:
        return self.plugin_cfg.get("group_chat_prompt", "")

    @property
    def group_proactive_chat(self) -> bool:
        return self.plugin_cfg.get("group_proactive_chat", False)

    @property
    def group_proactive_chat_probability(self) -> float:
        return self.plugin_cfg.get("group_proactive_chat_probability", 0.1)

    @property
    def waking_words(self) -> list[str]:
        return self.plugin_cfg.get("waking_words", [])

    def _session_allowed(self, key: str, sid: str) -> bool:
        """Apply a feature's session list, leaving existing configs unrestricted."""
        section = self.plugin_cfg.get(key, {})
        if not isinstance(section, dict):
            return False
        mode = str(section.get("permission_mode", "deny_list")).strip().lower()
        sessions = section.get("session_list", [])
        if mode not in ("allow_list", "deny_list") or not isinstance(sessions, list):
            return False
        sessions = [entry.strip() for entry in sessions if isinstance(entry, str)]
        return ListAccessPolicy.from_lists(
            mode, allow_list=sessions, deny_list=sessions,
        ).allows(sid)

    def _receives_unmentioned(self, sid: str) -> bool:
        return self.receive_unmentioned and self._session_allowed("receive_unmentioned_access", sid)

    async def initialize(self):
        self._terminating = False
        logger.info(f"[Default Chat] initialize")
    
    async def terminate(self):
        """Cancel all pending debounce tasks before the plugin is unloaded."""
        self._terminating = True
        tasks = list(self.session_tasks.values())
        self.session_tasks.clear()
        self.session_events.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @on.im_message(priority=Priority.HIGH)
    async def handle_msg(self, event: KiraMessageEvent):
        if self._terminating:
            return

        # === Check waking words ===
        for m in event.message.chain:
            if isinstance(m, Text) and any(w in m.text for w in self.waking_words):
                event.message.is_mentioned = True
                break

        sid = event.session.sid

        # Ignore unmentioned messages
        if not event.is_mentioned:
            if self._receives_unmentioned(sid):
                buffer = self.ctx.get_buffer(sid)
                if buffer.get_length() >= self.max_unmentioned_messages:
                    buffer.pop(count=buffer.get_length()-self.max_unmentioned_messages+1)
                event.buffer()
                if (
                    self.group_proactive_chat
                    and event.is_group_message()
                    and self._session_allowed("group_proactive_chat_access", sid)
                ):
                    if random.random() < self.group_proactive_chat_probability:
                        logger.info("[Chat] Triggered proactive chat")
                        event.flush()
            else:
                event.discard()
            return

        event.buffer()

        buffer_len = self.ctx.get_buffer(sid).get_length()
        if buffer_len + 1 >= self.max_buffer_messages:
            event.flush()
            return

        if sid not in self.session_events:
            self.session_events[sid] = asyncio.Event()
        if sid not in self.session_tasks:
            self.session_tasks[sid] = asyncio.create_task(
                self._debounce_loop(sid, self.session_events[sid]),
                name=f"chat_debounce_{sid}",
            )
        self.session_events[sid].set()

    async def _debounce_loop(self, sid: str, event: asyncio.Event):
        try:
            while True:
                if self._terminating:
                    return
                await event.wait()
                event.clear()
                await asyncio.sleep(self.debounce_interval)
                if self._terminating:
                    return
                if event.is_set() and not self._receives_unmentioned(sid):
                    continue
                buffer_len = self.ctx.get_buffer(sid).get_length()
                if buffer_len == 0:
                    return
                try:
                    await self.ctx.flush_session_messages(sid)
                except Exception:
                    logger.exception(f"[Debounce] Error flushing session {sid}")
                return
        except asyncio.CancelledError:
            raise
        finally:
            current_task = asyncio.current_task()
            if self.session_tasks.get(sid) is current_task:
                self.session_tasks.pop(sid, None)
                if event.is_set() and not self._terminating:
                    self.session_tasks[sid] = asyncio.create_task(
                        self._debounce_loop(sid, event),
                        name=f"chat_debounce_{sid}",
                    )
                else:
                    self.session_events.pop(sid, None)

    @on.llm_request(priority=Priority.MEDIUM)
    async def inject_group_prompt(self, event: KiraMessageBatchEvent, req: LLMRequest, *_):
        if not event.is_group_message():
            return
        if self.group_chat_prompt:
            for p in req.system_prompt:
                if p.name == "chat_env":
                    p.content += self.group_chat_prompt
                    break

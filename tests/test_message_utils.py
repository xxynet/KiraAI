import copy
import pytest

from core.chat.message_elements import Text, At, Image, Emoji, Notice, Poke, Sticker, Record
from core.chat.message_utils import MessageChain, KiraMessageEvent, KiraIMMessage
from core.chat.session import Session, User, Group


# ── MessageChain basics ─────────────────────────────────────────────

def test_chain_init_empty():
    c = MessageChain()
    assert c.is_empty()
    assert len(c) == 0
    assert bool(c) is False


def test_chain_init_with_elements():
    t1 = Text("a")
    t2 = Text("b")
    c = MessageChain([t1, t2])
    assert len(c) == 2
    assert bool(c) is True


def test_chain_getitem():
    t = Text("x")
    c = MessageChain([t])
    assert c[0] is t


def test_chain_setitem():
    t1 = Text("a")
    t2 = Text("b")
    c = MessageChain([t1])
    c[0] = t2
    assert c[0] is t2


def test_chain_delitem():
    c = MessageChain([Text("a"), Text("b")])
    del c[0]
    assert len(c) == 1
    assert c[0].text == "b"


def test_chain_contains():
    t = Text("hi")
    c = MessageChain([t])
    assert t in c
    assert Text("no") not in c


def test_chain_iter():
    elems = [Text("a"), Text("b")]
    c = MessageChain(elems)
    assert list(c) == elems


def test_chain_copy():
    t = Text("orig")
    c1 = MessageChain([t])
    c2 = c1.__copy__()
    assert c1 is not c2
    assert c1[0] is c2[0]
    assert len(c2) == 1


# ── MessageChain + operator ─────────────────────────────────────────

def test_chain_add_chain():
    c1 = MessageChain([Text("a")])
    c2 = MessageChain([Text("b")])
    c3 = c1 + c2
    assert len(c3) == 2
    assert c3[0].text == "a"
    assert c3[1].text == "b"


def test_chain_add_element():
    c1 = MessageChain([Text("a")])
    c2 = c1 + Text("b")
    assert len(c2) == 2
    assert c2[1].text == "b"


def test_chain_add_list():
    c1 = MessageChain([Text("a")])
    c2 = c1 + [Text("b"), Text("c")]
    assert len(c2) == 3


def test_chain_add_unsupported():
    c = MessageChain()
    with pytest.raises(TypeError):
        c + "string"


# ── MessageChain += operator ────────────────────────────────────────

def test_chain_iadd_chain():
    c = MessageChain([Text("a")])
    c += MessageChain([Text("b")])
    assert len(c) == 2


def test_chain_iadd_element():
    c = MessageChain([Text("a")])
    c += Text("b")
    assert len(c) == 2
    assert c[1].text == "b"


def test_chain_iadd_list():
    c = MessageChain()
    c += [Text("x")]
    assert len(c) == 1


def test_chain_iadd_unsupported():
    c = MessageChain()
    result = c.__iadd__("bad")
    assert result is NotImplemented


# ── MessageChain helper methods ─────────────────────────────────────

def test_chain_append():
    c = MessageChain()
    c.append(Text("x"))
    assert len(c) == 1


def test_chain_extend():
    c = MessageChain()
    c.extend([Text("a"), Text("b")])
    assert len(c) == 2


def test_chain_builder_text():
    c = MessageChain()
    c.text("hello")
    assert c[0].text == "hello"


def test_chain_builder_at():
    c = MessageChain()
    c.at("123", "Alice")
    assert c[0].pid == "123"


def test_chain_builder_emoji():
    c = MessageChain()
    c.emoji("e1")
    assert c[0].emoji_id == "e1"


def test_chain_builder_notice():
    c = MessageChain()
    c.notice("test notice")
    assert c[0].text == "test notice"


def test_chain_builder_poke():
    c = MessageChain()
    c.poke("user1")
    assert c[0].pid == "user1"


def test_chain_builder_sticker():
    c = MessageChain()
    c.message_list.append(Sticker(sticker_id="s1", sticker="https://example.com/sticker.png"))
    assert c[0].sticker_id == "s1"


def test_chain_builder_record():
    c = MessageChain()
    c.record("https://example.com/audio.mp3")
    assert c[0].file == "https://example.com/audio.mp3"


def test_chain_builder_reply_empty():
    c = MessageChain()
    c.reply("msg_1")
    assert len(c) == 1
    assert c[0].message_id == "msg_1"


def test_chain_builder_reply_non_empty():
    c = MessageChain([Text("hi")])
    c.reply("msg_1")
    assert len(c) == 1


# ── MessageChain repr ───────────────────────────────────────────────

def test_chain_repr():
    c = MessageChain([Text("a")])
    assert "MessageChain" in repr(c)


# ── KiraIMMessage ───────────────────────────────────────────────────

def test_im_message_is_group():
    msg = KiraIMMessage(
        message_id="m1", self_id="bot",
        chain=MessageChain(), timestamp=0,
        group=Group(group_id="g1"),
    )
    assert msg.is_group_message() is True


def test_im_message_is_not_group():
    msg = KiraIMMessage(
        message_id="m1", self_id="bot",
        chain=MessageChain(), timestamp=0,
    )
    assert msg.is_group_message() is False


# ── Session ─────────────────────────────────────────────────────────

def test_session_sid():
    s = Session(adapter_name="tg", session_type="gm", session_id="g1")
    assert s.sid == "tg:gm:g1"


def test_session_str():
    s = Session(adapter_name="tg", session_type="dm", session_id="u1")
    assert str(s) == "tg:dm:u1"


# ── KiraMessageEvent process_strategy ───────────────────────────────

def _make_event():
    user = User(user_id="u1", nickname="Alice")
    group = Group(group_id="g1", group_name="TestGroup")
    msg = KiraIMMessage(
        message_id="m1", self_id="bot",
        chain=MessageChain([Text("hi")]),
        timestamp=1, sender=user, group=group,
    )
    adapter = type("A", (), {"name": "test_adapter"})()
    return KiraMessageEvent(
        message_types=[], timestamp=1, message=msg, adapter=adapter
    )


def test_event_default_strategy_is_discard():
    evt = _make_event()
    assert evt.process_strategy == "discard"


def test_event_trigger():
    evt = _make_event()
    assert evt.trigger() is True
    assert evt.process_strategy == "trigger"


def test_event_buffer():
    evt = _make_event()
    assert evt.buffer() is True
    assert evt.process_strategy == "buffer"


def test_event_flush():
    evt = _make_event()
    assert evt.flush() is True
    assert evt.process_strategy == "flush"


def test_event_discard():
    evt = _make_event()
    evt.trigger()
    assert evt.discard() is True
    assert evt.process_strategy == "discard"


def test_event_force_locks_strategy():
    evt = _make_event()
    evt.trigger(force=True)
    assert evt.trigger() is False
    assert evt.buffer() is False
    assert evt.flush() is False
    assert evt.discard() is False
    assert evt.process_strategy == "trigger"


def test_event_stop():
    evt = _make_event()
    assert evt.is_stopped is False
    evt.stop()
    assert evt.is_stopped is True


def test_event_is_group_message():
    evt = _make_event()
    assert evt.is_group_message() is True


def test_event_properties():
    evt = _make_event()
    assert evt.extra is None
    assert evt.raw_message is None
    assert evt.is_mentioned is None
    assert evt.is_notice is False


def test_event_message_repr():
    evt = _make_event()
    assert "hi" in evt.message_repr

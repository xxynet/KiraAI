from core.adapter.src.qq.napcat_client.utils import QQMessageChain, QQMessageType


class UnknownElement:
    """Stands in for a chat element that has no QQ counterpart"""


def test_to_list_serialises_known_elements():
    chain = QQMessageChain([QQMessageType.Text("hello"), QQMessageType.At(123)])
    assert chain.to_list() == [
        {"type": "text", "data": {"text": "hello"}},
        {"type": "at", "data": {"qq": "123"}},
    ]


def test_to_list_skips_unknown_elements_without_dropping_the_rest():
    chain = QQMessageChain([QQMessageType.Text("hello"), UnknownElement()])
    serialised = chain.to_list()
    assert serialised == [{"type": "text", "data": {"text": "hello"}}]


def test_unsupported_elements_reports_unserialisable_elements():
    unknown = UnknownElement()
    chain = QQMessageChain([QQMessageType.Text("hello"), unknown])
    assert chain.unsupported_elements() == [unknown]


def test_unsupported_elements_empty_for_known_chain():
    chain = QQMessageChain([
        QQMessageType.Text("hello"),
        QQMessageType.Image(url="https://example.com/a.png"),
        QQMessageType.Reply(42),
    ])
    assert chain.unsupported_elements() == []

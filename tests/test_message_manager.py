from core.message_manager import SessionBuffer


def _make_buffer(messages):
    buffer = SessionBuffer()
    for message in messages:
        buffer.add(message)
    return buffer


def test_session_buffer_flush_with_filter():
    buffer = _make_buffer([1, 2, 3, 4])

    flushed = buffer.flush(filter_fn=lambda message: message % 2 == 0)

    assert flushed == [2, 4]
    assert buffer.buffer == [1, 3]


def test_session_buffer_filter_takes_precedence_over_count():
    buffer = _make_buffer([1, 2, 3, 4, 6])

    flushed = buffer.flush(count=2, filter_fn=lambda message: message % 2 == 0)

    assert flushed == [2, 4, 6]
    assert buffer.buffer == [1, 3]


def test_session_buffer_flush_with_count_when_filter_is_missing():
    buffer = _make_buffer([1, 2, 3, 4])

    flushed = buffer.flush(count=2)

    assert flushed == [1, 2]
    assert buffer.buffer == [3, 4]


def test_session_buffer_flushes_all_by_default():
    buffer = _make_buffer([1, 2, 3])

    flushed = buffer.flush()

    assert flushed == [1, 2, 3]
    assert buffer.buffer == []


def test_session_buffer_flush_with_filter_keeps_buffer_when_none_match():
    buffer = _make_buffer([1, 3, 5])

    flushed = buffer.flush(filter_fn=lambda message: message % 2 == 0)

    assert flushed == []
    assert buffer.buffer == [1, 3, 5]

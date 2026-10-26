import io
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import core.logging_manager as lm
from core.logging_manager import (
    LogCacheManager,
    LogQueueHandler,
    GetLoggerFilter,
    get_logger,
    setup_logging,
    _get_shared_file_handler,
    logger_color_mapping,
    _created_by_get_logger,
)


@pytest.fixture(autouse=True)
def _clean_logging_state():
    """Reset global logging state between tests."""
    saved = {
        "shared": lm._shared_file_handler,
        "level": lm._log_level,
        "path": lm._log_file_path,
        "max_size": lm._log_file_max_size,
        "created": lm._created_by_get_logger.copy(),
        "colors": lm.logger_color_mapping.copy(),
    }
    lm._shared_file_handler = None
    lm._log_level = "INFO"
    lm._log_file_path = None
    lm._log_file_max_size = 10
    lm._created_by_get_logger.clear()
    lm.logger_color_mapping.clear()
    yield
    # Restore and clean up loggers created during test
    for name in list(lm._created_by_get_logger):
        logger = logging.getLogger(name)
        logger.handlers.clear()
    lm._shared_file_handler = saved["shared"]
    lm._log_level = saved["level"]
    lm._log_file_path = saved["path"]
    lm._log_file_max_size = saved["max_size"]
    lm._created_by_get_logger.clear()
    lm._created_by_get_logger.update(saved["created"])
    lm.logger_color_mapping.clear()
    lm.logger_color_mapping.update(saved["colors"])


# ── LogCacheManager ──────────────────────────────────────────────


class TestLogCacheManager:
    def test_emit_adds_to_cache(self):
        mgr = LogCacheManager()
        mgr.emit("12:00:00", "INFO", "test", "hello", "blue")
        assert len(mgr.log_cache) == 1
        entry = mgr.log_cache[0]
        assert entry["time"] == "12:00:00"
        assert entry["level"] == "INFO"
        assert entry["name"] == "test"
        assert entry["message"] == "hello"
        assert entry["color"] == "blue"

    def test_cache_respects_max_size(self):
        mgr = LogCacheManager()
        for i in range(120):
            mgr.emit(f"t{i}", "INFO", "test", f"msg{i}", "blue")
        assert len(mgr.log_cache) == 100  # MAX_QUEUE_SIZE
        assert mgr.log_cache[0]["message"] == "msg20"  # earliest evicted

    def test_add_remove_queue(self):
        mgr = LogCacheManager()
        q = mgr.add_queue()
        assert q in mgr.queues
        mgr.remove_queue(q)
        assert q not in mgr.queues

    def test_emit_pushes_to_queues(self):
        mgr = LogCacheManager()
        q = mgr.add_queue()
        mgr.emit("12:00:00", "ERROR", "test", "boom", "red")
        assert not q.empty()
        item = q.get_nowait()
        assert item["message"] == "boom"

    def test_get_cache_returns_copy(self):
        mgr = LogCacheManager()
        mgr.emit("t", "INFO", "test", "msg", "blue")
        cache = mgr.get_cache()
        cache.clear()
        assert len(mgr.log_cache) == 1  # original untouched


# ── GetLoggerFilter ──────────────────────────────────────────────


class TestGetLoggerFilter:
    def test_allows_registered_name(self):
        names = {"myapp"}
        f = GetLoggerFilter(names)
        record = logging.LogRecord("myapp", logging.INFO, "", 0, "hi", (), None)
        assert f.filter(record) is True

    def test_rejects_unknown_name(self):
        names = {"myapp"}
        f = GetLoggerFilter(names)
        record = logging.LogRecord("other", logging.INFO, "", 0, "hi", (), None)
        assert f.filter(record) is False


# ── LogQueueHandler ──────────────────────────────────────────────


class TestLogQueueHandler:
    def test_emit_uses_formatter_datefmt(self):
        """emit() must set record.asctime via the formatter, not rely on
        other handlers running first."""
        import time

        mgr = LogCacheManager()
        qh = LogQueueHandler(mgr)
        fmt = logging.Formatter(datefmt="%Y-%m-%d %H:%M:%S")
        qh.setFormatter(fmt)

        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "hello", (), None
        )
        # Record should NOT have asctime yet
        assert not hasattr(record, "asctime")

        qh.emit(record)

        assert len(mgr.log_cache) == 1
        entry = mgr.log_cache[0]
        # asctime should be set and look like a timestamp
        assert entry["time"]  # non-empty
        assert "-" in entry["time"]  # contains date separators

    def test_emit_no_asctime_attribute_error(self):
        """emit() must never raise AttributeError on record.asctime,
        even when no previous handler has formatted the record."""
        mgr = LogCacheManager()
        qh = LogQueueHandler(mgr)
        qh.setFormatter(logging.Formatter(datefmt="%H:%M:%S"))

        record = logging.LogRecord(
            "x", logging.WARNING, "", 0, "msg", (), None
        )
        # Should not raise
        qh.emit(record)
        assert mgr.log_cache[0]["time"]  # populated

    def test_emit_with_format_without_asctime(self):
        """Formatter whose format string has no %(asctime)s should still
        produce a timestamp in the cache entry."""
        mgr = LogCacheManager()
        qh = LogQueueHandler(mgr)
        qh.setFormatter(logging.Formatter("%(message)s", datefmt="%H:%M:%S"))

        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0, "detail", (), None
        )
        qh.emit(record)
        assert mgr.log_cache[0]["time"]  # non-empty


# ── _get_shared_file_handler ─────────────────────────────────────


class TestSharedFileHandler:
    def test_singleton_returns_same_instance(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        h1 = _get_shared_file_handler()
        h2 = _get_shared_file_handler()
        assert h1 is h2

    def test_creates_rotating_handler(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        h = _get_shared_file_handler()
        assert isinstance(h, RotatingFileHandler)
        assert h.maxBytes == 10 * 1024 * 1024  # default 10 MB
        assert h.backupCount == 5

    def test_uses_configured_max_size(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        lm._log_file_max_size = 25
        h = _get_shared_file_handler()
        assert h.maxBytes == 25 * 1024 * 1024

    def test_formatter_includes_asctime(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        h = _get_shared_file_handler()
        assert "%(asctime)s" in h.formatter._fmt


# ── get_logger ───────────────────────────────────────────────────


class TestGetLogger:
    def test_creates_logger_with_three_handlers(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_a", "green")

        assert logger.name == "test_a"
        assert len(logger.handlers) == 3
        assert isinstance(logger.handlers[0], logging.StreamHandler)  # console
        assert isinstance(logger.handlers[1], MagicMock)  # shared fh
        assert isinstance(logger.handlers[2], LogQueueHandler)

    def test_returns_same_logger_on_second_call(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            l1 = get_logger("test_b", "blue")
            l2 = get_logger("test_b", "red")

        assert l1 is l2
        assert len(l1.handlers) == 3  # no duplicate handlers

    def test_registers_color_mapping(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            get_logger("test_c", "orange")

        assert logger_color_mapping["test_c"] == "orange"

    def test_registers_in_created_set(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            get_logger("test_d", "blue")

        assert "test_d" in _created_by_get_logger

    def test_propagate_is_false(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_e", "blue")

        assert logger.propagate is False

    def test_handler_order_is_ch_then_fh_then_qh(self):
        """Console handler must come before shared file handler, which must
        come before LogQueueHandler. This ensures record.asctime is set
        by the file handler's formatter before LogQueueHandler.emit() reads it."""
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_order", "green")

        handlers = logger.handlers
        assert isinstance(handlers[0], logging.StreamHandler)
        assert isinstance(handlers[1], MagicMock)  # shared fh mock
        assert isinstance(handlers[2], LogQueueHandler)

    def test_queue_handler_level_is_debug(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_f", "blue")

        qh = logger.handlers[2]
        assert qh.level == logging.DEBUG


# ── setup_logging ────────────────────────────────────────────────


class TestSetupLogging:
    def test_updates_created_loggers_level(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_setup_a", "blue")

        setup_logging(log_level="ERROR")

        # Console handler level should be updated
        console_handler = logger.handlers[0]
        assert console_handler.level == logging.ERROR

    def test_replaces_shared_handler_on_path_change(self, tmp_path):
        lm._log_file_path = str(tmp_path / "first.log")
        old_handler = _get_shared_file_handler()

        setup_logging(log_file_path=str(tmp_path / "second.log"))
        new_handler = lm._shared_file_handler

        assert new_handler is not old_handler
        assert new_handler.baseFilename == str(
            Path(tmp_path / "second.log").resolve()
        )

    def test_removes_stale_handlers_from_loggers(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            shared = _get_shared_file_handler()
            mock_fh.return_value = shared
            logger = get_logger("test_stale", "blue")

        # Simulate stale handler: create a different RotatingFileHandler
        stale = RotatingFileHandler(str(tmp_path / "test.log"))
        logger.handlers.insert(1, stale)

        setup_logging(log_file_path=str(tmp_path / "test.log"))

        # Stale handler should be removed
        for h in logger.handlers:
            if isinstance(h, RotatingFileHandler):
                assert h is lm._shared_file_handler

    def test_ensures_shared_handler_attached(self, tmp_path):
        lm._log_file_path = str(tmp_path / "test.log")
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            shared = _get_shared_file_handler()
            mock_fh.return_value = shared
            logger = get_logger("test_attach", "blue")

        # Remove shared handler manually
        logger.handlers = [logger.handlers[0], logger.handlers[2]]

        setup_logging(log_file_path=str(tmp_path / "test.log"))
        assert lm._shared_file_handler in logger.handlers

    def test_invalid_level_defaults_to_info(self):
        with patch("core.logging_manager._get_shared_file_handler") as mock_fh:
            mock_fh.return_value = MagicMock(spec=RotatingFileHandler)
            logger = get_logger("test_invalid_level", "blue")

        setup_logging(log_level="INVALID")
        assert logger.handlers[0].level == logging.INFO

    def test_silences_mcp_debug_logger(self):
        mcp_logger = logging.getLogger("mcp")
        previous_level = mcp_logger.level
        try:
            mcp_logger.setLevel(logging.DEBUG)
            setup_logging(log_level="DEBUG")
            assert mcp_logger.level == logging.WARNING
        finally:
            mcp_logger.setLevel(previous_level)
    def test_invalid_max_size_defaults_to_10(self, tmp_path):
        setup_logging(log_file_max_size="not_a_number")
        assert lm._log_file_max_size == 10


@pytest.fixture
def control_character_logger(tmp_path, monkeypatch):
    """Create isolated project handlers with color output enabled for assertions."""
    cache = LogCacheManager()
    monkeypatch.setattr(lm, "log_cache_manager", cache)
    log_path = tmp_path / "controls.log"
    lm._log_file_path = str(log_path)
    console = io.StringIO()
    logger_name = "test_controls\x07\x1b[2J"
    existing_logger = logging.getLogger(logger_name)
    for handler in existing_logger.handlers[:]:
        existing_logger.removeHandler(handler)
    monkeypatch.setenv("FORCE_COLOR", "1")
    with patch("sys.stderr", console):
        logger = get_logger(logger_name, "blue")
    try:
        yield logger, console, log_path, cache
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


class TestControlCharacterLogging:
    def test_fixture_replaces_existing_handlers(self, request, monkeypatch):
        """Initialize project handlers even when another formatter is already attached."""
        existing_logger = logging.getLogger("test_controls\x07\x1b[2J")
        existing_handler = logging.StreamHandler(io.StringIO())
        existing_formatter = logging.Formatter("%(message)s")
        existing_handler.setFormatter(existing_formatter)
        existing_logger.addHandler(existing_handler)
        monkeypatch.setenv("NO_COLOR", "1")
        try:
            logger, console, log_path, cache = request.getfixturevalue("control_character_logger")
            assert existing_handler not in logger.handlers
            assert existing_handler.formatter is existing_formatter
            assert not hasattr(existing_formatter, "force_color")
            assert len(logger.handlers) == 3
            logger.info("probe: %s", "\x07")
            assert "\x1b[" in console.getvalue()
            assert r"probe: \x07" in console.getvalue()
            assert r"probe: \x07" in log_path.read_text(encoding="utf-8")
            assert cache.get_cache()[-1]["message"] == r"probe: \x07"
        finally:
            existing_logger.removeHandler(existing_handler)
            existing_handler.close()

    @pytest.mark.parametrize("payload", [
        "",
        "Normal application log message.",
        "中文日志🙂\n第二行\tvalue\r\n第三行",
        r"literal\x07\x1b[31m",
        "format\r\b\v\f\x00\x7f\x85\x9c",
        "普通日志内容" * 2048,
    ], ids=["empty", "ascii", "unicode_multiline", "literal_escapes", "formatting", "long_unicode"])
    def test_plain_text_bypasses_sgr_processing(self, payload):
        with patch.object(lm, "_LOG_SGR_PATTERN") as sgr_pattern:
            sgr_pattern.split.side_effect = AssertionError("Plain text must bypass SGR splitting")
            assert lm._escape_log_controls(payload) is payload

    def test_bell_after_long_plain_text_is_still_escaped(self):
        prefix = "普通日志内容" * 2048
        assert lm._escape_log_controls(prefix + "\x07") == prefix + r"\x07"

    @pytest.mark.parametrize(("payload", "expected"), [
        ("bell\x07", r"bell\x07"),
        ("clear\x1b[2J", r"clear\x1b[2J"),
        ("title\x1b]0;untrusted\x07", r"title\x1b]0;untrusted\x07"),
        ("clipboard\x1b]52;c;dGVzdA==\x1b\\", "clipboard\\x1b]52;c;dGVzdA==\\x1b\\"),
        ("overwrite\rhide\b", "overwrite\rhide\b"),
        ("c1\x9b2J\x9d0;title\x9c", "c1\\x9b2J\\x9d0;title\x9c"),
        ("nul\x00end\x7f", "nul\x00end\x7f"),
        ("answerback\x05", r"answerback\x05"),
        ("dcs\x90payload\x9c", "dcs\\x90payload\x9c"),
        ("sos\x98payload\x9c", "sos\\x98payload\x9c"),
        ("decid\x9a", r"decid\x9a"),
        ("pm\x9epayload\x9c", "pm\\x9epayload\x9c"),
        ("apc\x9fpayload\x9c", "apc\\x9fpayload\x9c"),
        ("color\x1b[31mred\x1b[0m", "color\x1b[31mred\x1b[0m"),
        ("bright\x1b[1;94;103mtext\x1b[m", "bright\x1b[1;94;103mtext\x1b[m"),
        ("indexed\x1b[38;5;208;48;5;17mtext", "indexed\x1b[38;5;208;48;5;17mtext"),
        ("rgb\x1b[38;2;255;128;0mtext", "rgb\x1b[38;2;255;128;0mtext"),
        ("rgb\x1b[48:2::255:128:0mtext", "rgb\x1b[48:2::255:128:0mtext"),
        ("c1color\x9b31mred\x9b0m", "c1color\x9b31mred\x9b0m"),
        ("\x1b[31m\x07\x1b]52;c;dGVzdA==\x07\x1b[0m",
         "\x1b[31m\\x07\\x1b]52;c;dGVzdA==\\x07\x1b[0m"),
        ("partial\x1b[31", r"partial\x1b[31"),
        ("cursor query\x1b[6n", r"cursor query\x1b[6n"),
        ("private\x1b[>4;2m", r"private\x1b[>4;2m"),
        ("private\x9b?1m", r"private\x9b?1m"),
        ("malformed\x1b[3\x071m", r"malformed\x1b[3\x071m"),
        ("windows\r\nline", "windows\r\nline"),
        ("format\v\f\x85\x9c", "format\v\f\x85\x9c"),
        (r"literal\x07\x1b", r"literal\x07\x1b"),
        ("中文🙂\nnext\tcolumn", "中文🙂\nnext\tcolumn"),
    ])
    def test_all_outputs_escape_controls(self, control_character_logger, payload, expected):
        logger, console, log_path, cache = control_character_logger
        queue = cache.add_queue()
        logger.info("payload: %s", payload)

        console_text = console.getvalue()
        assert "\x1b[" in console_text  # Project-generated colors remain enabled.
        assert f"payload: {expected}" in console_text
        sgr_pattern = r"(?:\x1b\[|\x9b)[0-9;:]*m"
        plain_console = re.sub(sgr_pattern, "", console_text)
        plain_expected = re.sub(sgr_pattern, "", expected)
        file_text = log_path.read_bytes().decode("utf-8").replace(os.linesep, "\n")
        assert plain_console.endswith(f"[test_controls\\x07\\x1b[2J] payload: {plain_expected}\n")
        assert "[test_controls\\x07\\x1b[2J]" in file_text
        assert f"payload: {expected}\n" in file_text
        uncolored_file = re.sub(sgr_pattern, "", file_text)
        assert not any(char in uncolored_file for char in "\x05\x07\x1b\x90\x98\x9a\x9b\x9d\x9e\x9f")
        entry = cache.get_cache()[-1]
        assert entry["message"] == f"payload: {expected}"
        assert entry["name"] == r"test_controls\x07\x1b[2J"
        assert queue.get_nowait() == entry

    @pytest.mark.parametrize("formatter_type", [lm._SafeFormatter, lm._SafeColoredFormatter])
    def test_safe_formatters_preserve_original_record(self, formatter_type):
        """Check record isolation without involving pytest's own capture handlers."""
        record = logging.LogRecord(
            "test_controls\x07\x1b[2J", logging.ERROR, __file__, 0, "failure: %s", ("\x07",),
            (ValueError, ValueError("bad\x07\r\x1b[2J"), None),
            sinfo="Stack: untrusted\x1b]0;title\x07",
        )
        original_fields = record.__dict__.copy()
        output = formatter_type("%(name)s %(message)s").format(record)
        assert record.__dict__ == original_fields
        assert r"test_controls\x07\x1b[2J failure: \x07" in output
        assert "ValueError: bad\\x07\r\\x1b[2J" in output
        assert r"Stack: untrusted\x1b]0;title\x07" in output
        assert "\x07" not in output

    def test_exception_and_stack_controls_are_escaped(self, control_character_logger):
        logger, console, log_path, cache = control_character_logger
        record = logging.LogRecord(
            logger.name, logging.ERROR, __file__, 0, "failure: %s", ("\x07",),
            (ValueError, ValueError("bad\x07\r\x1b[2J"), None),
            sinfo="Stack: untrusted\x1b]0;title\x07",
        )
        logger.handle(record)

        for output in (console.getvalue(), log_path.read_bytes().decode("utf-8").replace(os.linesep, "\n")):
            assert "failure: \\x07" in output
            assert "ValueError: bad\\x07\r\\x1b[2J" in output
            assert "Stack: untrusted\\x1b]0;title\\x07" in output
            assert "\x07" not in output
        assert cache.get_cache()[-1]["message"] == r"failure: \x07"
        assert record.msg == "failure: %s"
        assert record.args == ("\x07",)
        assert record.stack_info == "Stack: untrusted\x1b]0;title\x07"

    def test_preformatted_exception_is_escaped(self, control_character_logger):
        logger, console, log_path, _ = control_character_logger
        record = logging.LogRecord(logger.name, logging.ERROR, __file__, 0, "failure", (), None)
        record.exc_text = "cached exception\x07\x1b[2J"
        logger.handle(record)
        for output in (console.getvalue(), log_path.read_bytes().decode("utf-8").replace(os.linesep, "\n")):
            assert r"cached exception\x07\x1b[2J" in output
            assert "\x07" not in output
        assert record.exc_text == "cached exception\x07\x1b[2J"

    def test_controls_escaped_after_logging_reconfiguration(self, control_character_logger, tmp_path):
        logger, console, _, cache = control_character_logger
        new_path = tmp_path / "reconfigured.log"
        setup_logging(log_level="ERROR", log_file_path=str(new_path), log_file_max_size=1)
        logger.debug("hidden from console: %s", "\x07\x1b[2J")
        assert console.getvalue() == ""
        assert r"hidden from console: \x07\x1b[2J" in new_path.read_text(encoding="utf-8")
        assert cache.get_cache()[-1]["message"] == r"hidden from console: \x07\x1b[2J"
        lm._shared_file_handler.doRollover()
        logger.error("after rollover: %s", "\x07")
        assert r"after rollover: \x07" in new_path.read_text(encoding="utf-8")
        assert "\x07" not in console.getvalue()

    def test_cache_and_standalone_queue_escape_controls(self):
        cache = LogCacheManager()
        queue = cache.add_queue()
        cache.emit("12:00:00", "INFO", "source\x07", "direct\x07\x1b[2J", "blue")
        assert queue.get_nowait()["message"] == r"direct\x07\x1b[2J"
        assert cache.get_cache()[-1]["name"] == r"source\x07"
        handler = LogQueueHandler(cache)
        handler.setFormatter(logging.Formatter(datefmt="%H:%M:%S"))
        handler.emit(logging.LogRecord("source\x07", logging.INFO, "", 0, "%s", ("\x07\r",), None))
        assert queue.get_nowait()["message"] == "\\x07\r"

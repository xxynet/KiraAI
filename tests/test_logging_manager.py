import logging
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

    def test_invalid_max_size_defaults_to_10(self, tmp_path):
        setup_logging(log_file_max_size="not_a_number")
        assert lm._log_file_max_size == 10

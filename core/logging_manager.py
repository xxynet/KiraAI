import logging
import re
import sys
from asyncio import Queue
from collections import deque
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path

import colorlog
from colorlog.escape_codes import escape_codes

from core.utils.path_utils import get_data_path

sys.stdout.reconfigure(encoding='utf-8')

escape_codes['orange'] = '\033[38;5;208m'  # 208 是接近橙色的 ANSI 256 色编号

logger_color_mapping = {}

MAX_QUEUE_SIZE = 100

_log_level = "INFO"
_log_file_path = None
_log_file_max_size = 10  # MB

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# Allow numeric SGR styling; block bells, terminal queries, and other sequences.
_LOG_CONTROL_TRANSLATION = {
    code: f"\\x{code:02x}"
    for code in (
        0x05,  # ENQ: terminal answerback query.
        0x07,  # BEL: terminal bell.
        0x1b,  # ESC: seven-bit terminal sequence introducer.
        0x90,  # DCS: device control string.
        0x98,  # SOS: start of string.
        0x9a,  # DECID: terminal identification query.
        0x9b,  # CSI: control sequence introducer.
        0x9d,  # OSC: operating system command.
        0x9e,  # PM: privacy message.
        0x9f,  # APC: application program command.
    )
}


_LOG_SGR_PATTERN = re.compile(r"((?:\x1b\[|\x9b)[0-9;:]*m)")
_LOG_CONTROL_PATTERN = re.compile(
    "[" + re.escape("".join(chr(code) for code in _LOG_CONTROL_TRANSLATION)) + "]"
)


def _escape_log_controls(text: str) -> str:
    """Preserve ANSI SGR styling while escaping other terminal commands and bells."""
    if _LOG_CONTROL_PATTERN.search(text) is None:
        return text
    return "".join(
        segment if index % 2 else segment.translate(_LOG_CONTROL_TRANSLATION)
        for index, segment in enumerate(_LOG_SGR_PATTERN.split(text))
    )


class _SafeLogFormatterMixin:
    def format(self, record):
        # Escape untrusted fields before colorlog adds its own terminal colors.
        safe_record = copy(record)
        safe_record.msg = _escape_log_controls(record.getMessage())
        safe_record.args = ()
        safe_record.name = _escape_log_controls(record.name)
        safe_record.levelname = _escape_log_controls(record.levelname)
        if safe_record.exc_info and not safe_record.exc_text:
            safe_record.exc_text = self.formatException(safe_record.exc_info)
        if safe_record.exc_text:
            safe_record.exc_text = _escape_log_controls(safe_record.exc_text)
        if safe_record.stack_info:
            safe_record.stack_info = _escape_log_controls(safe_record.stack_info)
        return super().format(safe_record)


class _SafeFormatter(_SafeLogFormatterMixin, logging.Formatter):
    pass


class _SafeColoredFormatter(_SafeLogFormatterMixin, colorlog.ColoredFormatter):
    pass


class LogCacheManager:
    def __init__(self):
        self.log_cache: deque = deque(maxlen=MAX_QUEUE_SIZE)
        self.queues: list[Queue] = []

    def add_queue(self):
        que = Queue(maxsize=MAX_QUEUE_SIZE)
        self.queues.append(que)
        return que

    def remove_queue(self, que: Queue):
        self.queues.remove(que)

    def get_cache(self) -> list:
        """Get all logs from cache"""
        return list(self.log_cache)

    def emit(self, time, level, name, message, color):
        level = _escape_log_controls(level)
        name = _escape_log_controls(name)
        message = _escape_log_controls(message)
        # Add to cache
        self.log_cache.append({
            "time": time,
            "level": level,
            "name": name,
            "message": message,
            "color": color
        })
        
        # Send to all queues
        for que in self.queues:
            try:
                que.put_nowait({
                    "time": time,
                    "level": level,
                    "name": name,
                    "message": message,
                    "color": color
                })
            except Exception:
                pass


class LogQueueHandler(logging.Handler):
    def __init__(self, log_cache_mgr: LogCacheManager):
        super().__init__()
        self.log_cache_mgr = log_cache_mgr

    def emit(self, record) -> None:
        self.format(record)
        if not hasattr(record, "asctime"):
            record.asctime = self.formatter.formatTime(record, self.formatter.datefmt)
        self.log_cache_mgr.emit(
            record.asctime,
            record.levelname,
            record.name,
            record.getMessage(),
            logger_color_mapping.get(record.name, "blue")
        )


log_cache_manager = LogCacheManager()

# Shared file handler — one RotatingFileHandler for all loggers to avoid
# multiple handlers rotating the same file independently and losing logs.
_shared_file_handler = None


class GetLoggerFilter(logging.Filter):
    """过滤器：只允许通过get_logger创建的logger的日志通过"""

    def __init__(self, created_loggers_set):
        super().__init__()
        self.created_loggers_set = created_loggers_set

    def filter(self, record):
        # 如果logger名称在created_loggers_set中，则允许通过
        return record.name in self.created_loggers_set


_created_by_get_logger = set()


def _get_shared_file_handler() -> RotatingFileHandler:
    """Return the singleton RotatingFileHandler, creating it on first call."""
    global _shared_file_handler
    if _shared_file_handler is None:
        log_file = _log_file_path or f"{get_data_path()}/log.log"
        _shared_file_handler = RotatingFileHandler(
            filename=log_file, maxBytes=_log_file_max_size * 1024 * 1024, backupCount=5, encoding='utf-8'
        )
        _shared_file_handler.setLevel(logging.DEBUG)
        _shared_file_handler.setFormatter(_SafeFormatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    return _shared_file_handler


def setup_logging(log_level: str = "INFO", log_file_path: str | None = None, log_file_max_size: int = 10):
    """Called once after config is loaded to apply logging settings."""
    global _log_level, _log_file_path, _log_file_max_size, _shared_file_handler

    log_level = str(log_level) if log_level else "INFO"
    if log_level.upper() not in _LEVEL_MAP:
        log_level = "INFO"
    try:
        log_file_max_size = int(log_file_max_size)
    except (TypeError, ValueError):
        log_file_max_size = 10

    _log_level = log_level
    _log_file_path = log_file_path
    _log_file_max_size = log_file_max_size

    level = _LEVEL_MAP.get(log_level.upper(), logging.INFO)

    # MCP DEBUG responses can contain complete base64 media payloads.
    logging.getLogger("mcp").setLevel(logging.WARNING)

    log_file = str(Path(_log_file_path or f"{get_data_path()}/log.log").resolve())
    max_bytes = _log_file_max_size * 1024 * 1024

    # Replace shared file handler if path or size changed
    if _shared_file_handler is not None:
        if _shared_file_handler.baseFilename != log_file or _shared_file_handler.maxBytes != max_bytes:
            old = _shared_file_handler
            old.close()
            _shared_file_handler = RotatingFileHandler(
                filename=log_file, maxBytes=max_bytes, backupCount=5, encoding='utf-8'
            )
            _shared_file_handler.setLevel(logging.DEBUG)
            _shared_file_handler.setFormatter(old.formatter)

    for name in _created_by_get_logger:
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            # Remove any per-logger RotatingFileHandler from the old pattern
            if isinstance(handler, RotatingFileHandler) and handler is not _shared_file_handler:
                handler.close()
                logger.removeHandler(handler)
            elif isinstance(handler, logging.StreamHandler) and not isinstance(handler, LogQueueHandler):
                handler.setLevel(level)

        # Ensure the shared handler is attached
        if _shared_file_handler not in logger.handlers:
            logger.addHandler(_shared_file_handler)


def get_logger(name: str, color: str):
    logger = logging.getLogger(name)

    _created_by_get_logger.add(name)

    if logger.handlers:
        return logger

    logger_color_mapping[name] = color

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不传播到上级 logger
    console_formatter = _SafeColoredFormatter(
        '%(blue)s%(asctime)s%(reset)s %(log_color)s%(levelname)-8s%(reset)s'
        f'%({color})s[%(name)s]%(reset)s %({color})s%(message)s%(reset)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'bold_green',
            'WARNING': 'bold_yellow',
            'ERROR': 'bold_red',
            'CRITICAL': 'bold_red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    )

    level = _LEVEL_MAP.get(_log_level.upper(), logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(console_formatter)

    fh = _get_shared_file_handler()

    qh = LogQueueHandler(log_cache_manager)
    qh.setLevel(logging.DEBUG)
    qh.setFormatter(_SafeFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
    qh.addFilter(GetLoggerFilter(_created_by_get_logger))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.addHandler(qh)
    return logger

import logging
import colorlog
import sys
from colorlog.escape_codes import escape_codes
from logging.handlers import RotatingFileHandler

logging.getLogger("httpx").setLevel(logging.CRITICAL)

sys.stdout.reconfigure(encoding='utf-8')

escape_codes['orange'] = '\033[38;5;208m'  # 208 是接近橙色的 ANSI 256 色编号


def get_logger(name: str, color: str):
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不传播到上级 logger
    console_formatter = colorlog.ColoredFormatter(
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

    file_formatter = logging.Formatter(
        '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(console_formatter)

    fh = RotatingFileHandler(filename="log.log", maxBytes=10*1024*1024, backupCount=1, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

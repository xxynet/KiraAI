import logging
import colorlog
from colorlog.escape_codes import escape_codes

logging.getLogger("httpx").setLevel(logging.CRITICAL)

escape_codes['orange'] = '\033[38;5;208m'  # 208 是接近橙色的 ANSI 256 色编号


def get_logger(name: str, color: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不传播到上级 logger
    formatter = colorlog.ColoredFormatter(
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

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)

    logger.addHandler(ch)
    return logger

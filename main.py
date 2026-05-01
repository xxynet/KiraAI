import argparse
import asyncio
import os


kira_logo = r"""
      _  ___              _    ___ 
     | |/ (_)_ __ __ _   / \  |_ _|
     | ' /| | '__/ _` | / _ \  | | 
     | . \| | | | (_| |/ ___ \ | | 
     |_|\_\_|_|  \__,_/_/   \_\___|
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="KiraAI",
        description="KiraAI",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override the data directory (default: <cwd>/data)",
    )
    parser.add_argument(
        "--webui-dir",
        type=str,
        default=None,
        help="Override the frontend dist directory (default: <data-dir>/dist)",
    )
    parser.add_argument(
        "--ignore-webui-version-check",
        action="store_true",
        default=False,
        help="Skip frontend dist version check (useful during development with --webui-dir)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    # set script dir as working dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # parse CLI args and apply path overrides
    args = _parse_args()
    from core.utils.path_utils import init_paths, get_data_path

    init_paths(
        data_dir=args.data_dir,
        webui_dir=args.webui_dir,
    )

    sub_data_folders = ["config", "memory", "plugins", "files", "temp", "sticker", "skills"]
    for folder in sub_data_folders:
        os.makedirs(get_data_path() / folder, exist_ok=True)

    # init logging
    from core.logging_manager import get_logger
    logger = get_logger("launcher", "blue")

    for logo_line in kira_logo.split("\n"):
        logger.info(logo_line)

    logger.info(f"Set working dir: {script_dir}")
    if args.data_dir:
        logger.info(f"Using data dir override: {args.data_dir}")
    if args.webui_dir:
        logger.info(f"Using webui dir override: {args.webui_dir}")

    from core.launcher import KiraLauncher

    launcher = KiraLauncher(ignore_webui_version_check=args.ignore_webui_version_check)

    try:
        asyncio.run(launcher.start())
    except KeyboardInterrupt:
        pass

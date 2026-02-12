import asyncio
import os


kira_logo = r"""
      _  ___              _    ___ 
     | |/ (_)_ __ __ _   / \  |_ _|
     | ' /| | '__/ _` | / _ \  | | 
     | . \| | | | (_| |/ ___ \ | | 
     |_|\_\_|_|  \__,_/_/   \_\___|
"""


if __name__ == "__main__":
    # set script dir as working dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # init logging
    from core.logging_manager import get_logger
    logger = get_logger("launcher", "blue")

    for logo_line in kira_logo.split("\n"):
        logger.info(logo_line)

    logger.info(f"Set working dir: {script_dir}")

    from core.utils.path_utils import get_data_path

    sub_data_folders = ["config", "memory", "plugins", "files", "sticker"]
    for folder in sub_data_folders:
        os.makedirs(get_data_path() / folder, exist_ok=True)

    from core.launcher import KiraLauncher

    launcher = KiraLauncher()

    try:
        asyncio.run(launcher.start())
    except KeyboardInterrupt:
        pass

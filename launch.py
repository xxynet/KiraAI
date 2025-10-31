import asyncio
import os


if __name__ == "__main__":
    # set script dir as working dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # init logging
    from core.logging_manager import get_logger
    logger = get_logger("launcher", "blue")
    logger.info(f"Set working dir: {script_dir}")

    from core.main import main as core_main

    try:
        asyncio.run(core_main())
    except KeyboardInterrupt:
        logger.info("Exiting...")

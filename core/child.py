"""Child-process bootstrap: what `main.py --_child` runs.

The supervisor (core/supervisor.py) spawns main.py with --_child; this module
installs the child's signal handling, prepares the data directories, and hands
over to KiraLauncher.
"""

import argparse
import asyncio
import os
import signal

kira_logo = r"""
      _  ___              _    ___
     | |/ (_)_ __ __ _   / \  |_ _|
     | ' /| | '__/ _` | / _ \  | |
     | . \| | | | (_| |/ ___ \ | |
     |_|\_\_|_|  \__,_/_/   \_\___|
"""


def _install_child_signal_handlers() -> None:
    """Turn stop signals into the same shutdown path as Ctrl+C.

    Python's default SIGTERM disposition ends the process outright. uvicorn
    replaces these handlers while serving and, once the HTTP server has drained,
    restores the previous ones and re-raises every captured signal
    (uvicorn.server.Server.capture_signals). With the default handler restored
    that re-raise kills the process before KiraLauncher reaches
    `lifecycle.stop()`; with the handler below it surfaces as a
    KeyboardInterrupt, which the launcher already handles gracefully.

    The handler fires once on purpose: a duplicate signal (uvicorn re-raising,
    or the supervisor forwarding the same stop) must not abort a shutdown that
    is already in progress. A second Ctrl+C reaching the supervisor escalates to
    an immediate kill instead.
    """
    fired = False

    def _on_stop(sig, frame):
        nonlocal fired
        if fired:
            return
        fired = True
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_stop)
        except (ValueError, OSError):
            pass  # not the main thread / unsupported platform


def run_child(args: argparse.Namespace):
    """Run the actual application (called in the child process)."""
    _install_child_signal_handlers()

    if args.env:
        os.environ["KIRA_ENV"] = args.env
    if args.telemetry_server:
        os.environ["KIRA_TELEMETRY_SERVER"] = args.telemetry_server

    from core.utils.path_utils import init_paths, get_data_path

    init_paths(data_dir=args.data_dir, webui_dir=args.webui_dir)

    for folder in ["config", "memory", "plugins", "files", "temp", "sticker", "skills"]:
        os.makedirs(get_data_path() / folder, exist_ok=True)

    from core.logging_manager import get_logger
    logger = get_logger("launcher", "blue")

    for logo_line in kira_logo.split("\n"):
        logger.info(logo_line)

    logger.info(f"Working dir: {os.getcwd()}")
    if args.data_dir:
        logger.info(f"Using data dir override: {args.data_dir}")
    if args.webui_dir:
        logger.info(f"Using webui dir override: {args.webui_dir}")
    if args.disable_webui_auth:
        logger.info("WebUI authentication disabled")

    from core.launcher import KiraLauncher

    launcher = KiraLauncher(
        ignore_webui_version_check=args.ignore_webui_version_check,
        disable_webui_auth=args.disable_webui_auth,
    )

    try:
        asyncio.run(launcher.start())
    except KeyboardInterrupt:
        pass

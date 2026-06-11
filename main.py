import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


kira_logo = r"""
      _  ___              _    ___ 
     | |/ (_)_ __ __ _   / \  |_ _|
     | ' /| | '__/ _` | / _ \  | | 
     | . \| | | | (_| |/ ___ \ | | 
     |_|\_\_|_|  \__,_/_/   \_\___|
"""

RESTART_EXIT_CODE = 42
DEFAULT_PORT = 5267
MAX_RESTARTS = 10
RESTART_BACKOFF_BASE = 2  # seconds
STABLE_RUN_SECONDS = 30  # child running this long resets the restart counter


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
    parser.add_argument(
        "--env",
        type=str,
        choices=["dev", "prod"],
        default=None,
        help="Set environment mode: 'dev' enables API docs/access log; 'prod' disables them (default: prod, also reads KIRA_ENV env var)",
    )
    parser.add_argument(
        "--disable-webui-auth",
        action="store_true",
        default=False,
        help="Disable WebUI authentication (use a fixed token so Electron can auto-login)",
    )
    parser.add_argument(
        "--telemetry-server",
        type=str,
        default=None,
        help="Override the telemetry server URL (also reads KIRA_TELEMETRY_SERVER env var)",
    )
    parser.add_argument(
        "--_child",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def _recover_bak_files(root_path: Path):
    """Recover from any incomplete update left by a previous crash."""
    import shutil
    for bak in root_path.glob("*.bak"):
        original = bak.with_suffix("")
        if original.exists():
            if bak.is_dir():
                shutil.rmtree(bak)
            else:
                bak.unlink()
        else:
            bak.rename(original)


def _get_port(data_path: Path) -> int:
    config_path = data_path / "webui.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f).get("port", DEFAULT_PORT)
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_PORT


def _wait_for_port_release(port: int, timeout: float = 15.0):
    """Block until the given TCP port is free or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return  # port is free
        except OSError:
            return
        time.sleep(0.5)


def _run_child(args: argparse.Namespace):
    """Run the actual application (called in the child process)."""
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


def _run_supervisor(args: argparse.Namespace):
    """Supervisor loop: spawn child process, restart on exit code 42."""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    from core.utils.path_utils import init_paths, get_data_path

    init_paths(data_dir=args.data_dir, webui_dir=args.webui_dir)

    for folder in ["config", "memory", "plugins", "files", "temp", "sticker", "skills"]:
        os.makedirs(get_data_path() / folder, exist_ok=True)

    _recover_bak_files(Path(script_dir))

    port = _get_port(get_data_path())

    # Build child command
    child_cmd = [sys.executable, os.path.join(script_dir, "main.py"), "--_child"]
    if args.data_dir:
        child_cmd += ["--data-dir", args.data_dir]
    if args.webui_dir:
        child_cmd += ["--webui-dir", args.webui_dir]
    if args.ignore_webui_version_check:
        child_cmd.append("--ignore-webui-version-check")
    if args.disable_webui_auth:
        child_cmd.append("--disable-webui-auth")
    if args.env:
        child_cmd += ["--env", args.env]
    if args.telemetry_server:
        child_cmd += ["--telemetry-server", args.telemetry_server]

    restart_count = 0

    while True:
        child = subprocess.Popen(child_cmd, cwd=script_dir)
        child_start = time.monotonic()
        try:
            child.wait()
        except KeyboardInterrupt:
            child.terminate()
            child.wait()
            sys.exit(0)
        elapsed = time.monotonic() - child_start

        if child.returncode != RESTART_EXIT_CODE:
            break

        # Child ran long enough — treat as a stable run, reset counter
        if elapsed >= STABLE_RUN_SECONDS:
            restart_count = 0

        restart_count += 1
        if restart_count > MAX_RESTARTS:
            print(f"[supervisor] Exceeded {MAX_RESTARTS} rapid restarts, exiting.")
            break

        backoff = min(RESTART_BACKOFF_BASE * restart_count, 60)
        print(f"[supervisor] Restart {restart_count}/{MAX_RESTARTS} in {backoff}s ...")
        time.sleep(backoff)

        _wait_for_port_release(port)

    sys.exit(child.returncode or 0)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    args = _parse_args()

    if args._child:
        _run_child(args)
    else:
        _run_supervisor(args)

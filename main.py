import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import math
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
WAIT_SLICE_SECONDS = 0.25  # wait granularity; caps how late a stop signal is noticed
FORCE_KILL_WAIT_SECONDS = 5.0  # how long to wait for the child to die after a kill


def _env_float(name: str, default: float) -> float:
    """Read a positive float from the environment, else fall back to default.

    A bad value must not take the supervisor down (it is the container's PID 1,
    so raising here would crash-loop the container), but it must not silently
    change stop behaviour either: 0 or a negative value removes the grace period
    (the child is killed immediately) and NaN/inf make it never expire.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        print(f"[supervisor] {name}={raw!r} is not a positive number, using {default}")
        return default
    return value


# How long the child gets to finish its own shutdown before it is killed. Keep
# this below the stop timeout of whatever supervises us (docker stop -t defaults
# to 10s, systemd TimeoutStopSec to 90s), otherwise the runtime SIGKILLs us
# before the grace period has been used.
STOP_GRACE_SECONDS = _env_float("KIRA_STOP_GRACE", 8.0)

# Windows only: give the child its own process group so a stop can be forwarded
# with CTRL_BREAK_EVENT. Off by default because the console already delivers
# Ctrl+C to both processes.
_CHILD_NEW_GROUP = os.environ.get("KIRA_CHILD_NEW_GROUP") == "1"


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
    from core.utils.update_transaction import recover_interrupted_update

    for message in recover_interrupted_update(root_path):
        print(f"[supervisor] {message}")

    # Backups from releases before transaction journaling are ambiguous when the
    # destination still exists. Keep those files rather than risking a restore
    # over a newer file. New updates use a dedicated transaction backup folder.
    for bak in root_path.glob("*.bak"):
        original = bak.with_suffix("")
        if original.exists():
            print(f"[supervisor] Leaving ambiguous legacy backup: {bak.name}")
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


def _wait_for_port_release(port: int, timeout: float = 15.0, should_stop=None):
    """Block until the given TCP port is free or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if should_stop is not None and should_stop():
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return  # port is free
        except OSError:
            return
        time.sleep(0.5)


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


def _run_child(args: argparse.Namespace):
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


class _StopState:
    """Stop requests seen by the supervisor.

    Signal handlers only set flags. Raising an exception from a handler would
    abort whatever happens to be running (including the grace period) and cannot
    deliver the request any earlier than the flag does.
    """

    __slots__ = ("requested", "force", "signal")

    def __init__(self) -> None:
        self.requested = False
        self.force = False
        self.signal = None

    def on_signal(self, sig, frame) -> None:
        self.force = self.requested  # a second signal escalates immediately
        self.requested = True
        if self.signal is None:
            self.signal = sig


def _install_stop_handlers(state: _StopState) -> None:
    """Handle SIGINT (terminal), SIGTERM (service manager / container runtime)
    and SIGBREAK (Windows console close).

    This is what makes `docker stop` work at all: as PID 1 the kernel ignores the
    default SIGTERM action, so without a handler the container would only ever be
    stopped by the runtime's SIGKILL.
    """
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, state.on_signal)
        except (ValueError, OSError):
            pass


def _wait_for_child_exit(child, seconds, should_stop) -> bool:
    """Wait for the child in slices: True if it exited, False on timeout or when
    should_stop() asks us to give up.

    Never block in child.wait() without a timeout. On Windows that wait is a bare
    WaitForSingleObject() which does not observe CPython's SIGINT event, so an
    unbounded wait silently swallows stop signals until the child exits by
    itself.
    """
    deadline = None if seconds is None else time.monotonic() + seconds
    while True:
        if child.poll() is not None:
            return True
        if should_stop():
            return False
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return False
        timeout = WAIT_SLICE_SECONDS if remaining is None else min(WAIT_SLICE_SECONDS, remaining)
        try:
            child.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            continue


def _forward_stop(child) -> str:
    """Pass the stop request on to the child and report what was done.

    A terminal signal reaches the child by itself (same process group / console),
    but a service manager or container runtime signals only us, so the request
    has to be forwarded or the child never learns it should stop.
    """
    if os.name == "nt":
        if not _CHILD_NEW_GROUP:
            return "child shares the console, it received the interrupt itself"
        try:
            child.send_signal(signal.CTRL_BREAK_EVENT)  # needs its own process group
            return "CTRL_BREAK_EVENT"
        except (OSError, ValueError) as exc:
            return f"CTRL_BREAK_EVENT failed: {exc}"
    try:
        child.send_signal(signal.SIGTERM)  # the child treats it as a graceful stop
        return "SIGTERM"
    except OSError as exc:
        return f"SIGTERM failed: {exc}"


def _stop_child(child, state: _StopState) -> None:
    """Stop the child: forward the request, allow the grace period, then kill."""
    print(f"[supervisor] Stop requested (signal {state.signal}): {_forward_stop(child)}")

    if _wait_for_child_exit(child, STOP_GRACE_SECONDS, lambda: state.force):
        print(f"[supervisor] Child exited gracefully (code={child.poll()}).")
        return

    if state.force:
        print("[supervisor] Second stop signal received, killing the child.")
    else:
        print(f"[supervisor] Child still running after {STOP_GRACE_SECONDS:.0f}s, killing it.")
    try:
        child.kill()  # SIGKILL on POSIX, TerminateProcess on Windows
    except OSError as exc:
        print(f"[supervisor] Failed to kill child: {exc}")
        return
    if _wait_for_child_exit(child, FORCE_KILL_WAIT_SECONDS, lambda: False):
        print(f"[supervisor] Child killed (code={child.poll()}).")
    else:
        print("[supervisor] Child still running after kill, giving up waiting.")


def _sleep_interruptible(seconds: float, state: _StopState) -> bool:
    """Sleep for the restart backoff, waking up early on a stop request."""
    deadline = time.monotonic() + seconds
    while not state.requested:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(WAIT_SLICE_SECONDS, remaining))
    return state.requested


def _run_supervisor(args: argparse.Namespace):
    """Supervisor loop: spawn child, restart on exit code 42, stop gracefully.

    A stop request is forwarded to the child, which gets STOP_GRACE_SECONDS to
    finish its own shutdown before it is killed.
    """
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
    state = _StopState()
    _install_stop_handlers(state)

    popen_kwargs = {}
    if os.name == "nt" and _CHILD_NEW_GROUP:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    while True:
        if state.requested:  # stop requested while we were between children
            print("[supervisor] Stop requested, exiting.")
            sys.exit(0)

        child = subprocess.Popen(child_cmd, cwd=script_dir, **popen_kwargs)
        child_start = time.monotonic()

        # Wait in slices so a stop signal is noticed while the child is still
        # shutting down, instead of only after it has exited on its own.
        if not _wait_for_child_exit(child, None, lambda: state.requested):
            _stop_child(child, state)
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

        # Exponential backoff capped at 60s. restart_count is already 1 on the
        # first restart, so 2 ** (restart_count - 1) makes the first backoff
        # equal to RESTART_BACKOFF_BASE.
        backoff = min(RESTART_BACKOFF_BASE * (2 ** (restart_count - 1)), 60)
        print(f"[supervisor] Restart {restart_count}/{MAX_RESTARTS} in {backoff}s ...")
        if _sleep_interruptible(backoff, state):
            print("[supervisor] Stop requested, exiting.")
            sys.exit(0)

        _wait_for_port_release(port, should_stop=lambda: state.requested)

    sys.exit(child.returncode or 0)


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    args = _parse_args()

    if args._child:
        _run_child(args)
    else:
        _run_supervisor(args)

"""KiraAI entry point.

By default this process is the supervisor (core/supervisor.py): it spawns
`python main.py --_child`, restarts the child when it exits with
RESTART_EXIT_CODE (self-restart after updates) and forwards stop signals.
With --_child it runs the application itself (core/child.py).

Keep this file stdlib-only and let it import core.* lazily: it is the
container's PID 1, so it must still start when core/ is mid-update.
"""

import argparse
import os


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


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    args = _parse_args()

    if args._child:
        from core.child import run_child

        run_child(args)
    else:
        from core.supervisor import run_supervisor

        run_supervisor(args, script_dir)

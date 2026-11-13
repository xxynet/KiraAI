import ctypes
import os
import subprocess
import sys


def main() -> None:
    # The parent sends the command only after assigning this process to its job.
    command = sys.stdin.buffer.read().decode("utf-8", "surrogatepass")
    if command:
        result = subprocess.run(command, shell=True, stdin=subprocess.DEVNULL, check=False)
        os._exit(ctypes.c_int32(result.returncode).value)


if __name__ == "__main__":
    main()

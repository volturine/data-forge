#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from typing import Sequence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a command with a timeout and heartbeat logs.')
    parser.add_argument('--timeout-seconds', type=int, default=0)
    parser.add_argument('--grace-seconds', type=int, default=30)
    parser.add_argument('--heartbeat-seconds', type=int, default=0)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    return parser.parse_args()


def normalize_command(raw: Sequence[str]) -> list[str]:
    command = list(raw)
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise SystemExit("run_with_timeout.py requires a command after '--'")
    return command


class ForwardSignals:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self._previous: dict[int, object] = {}

    def __enter__(self) -> 'ForwardSignals':
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)

    def _handle(self, signum: int, _frame: object) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signum)


def main() -> int:
    args = parse_args()
    command = normalize_command(args.command)
    process = subprocess.Popen(command)
    started = time.monotonic()
    next_heartbeat = started + args.heartbeat_seconds if args.heartbeat_seconds > 0 else float('inf')

    with ForwardSignals(process):
        while True:
            returncode = process.poll()
            if returncode is not None:
                return returncode

            now = time.monotonic()
            elapsed = int(now - started)
            if args.heartbeat_seconds > 0 and now >= next_heartbeat:
                print(f'[e2e] Playwright still running after {elapsed}s', flush=True)
                next_heartbeat += args.heartbeat_seconds

            if args.timeout_seconds > 0 and elapsed >= args.timeout_seconds:
                print(
                    f'[e2e] command hit timeout after {args.timeout_seconds}s',
                    file=sys.stderr,
                    flush=True,
                )
                process.terminate()
                try:
                    process.wait(timeout=args.grace_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 124

            time.sleep(0.2)


if __name__ == '__main__':
    raise SystemExit(main())

from __future__ import annotations

import argparse
import io
import itertools
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PATTERNS = [
    'Warning:',
    ' - WARNING - ',
    'Traceback',
    'UnhandledPromiseRejection',
    'DeprecationWarning',
    'ResourceWarning',
    'ERROR',
    'EPIPE',
    'ECONNRESET',
]


@dataclass(frozen=True)
class Match:
    pattern: str
    line_number: int
    line: str


def _scan(stdout: io.TextIOBase, stderr: io.TextIOBase, ignore_patterns: list[str]) -> Iterator[Match]:
    for line_number, line in enumerate(itertools.chain(stdout, stderr), start=1):
        line = line.rstrip('\n')
        if any(pattern in line for pattern in ignore_patterns):
            continue
        for pattern in DEFAULT_PATTERNS:
            if pattern in line:
                yield Match(pattern=pattern, line_number=line_number, line=line)
                break


def _pipe_stream(stream: io.TextIOBase | None, target: io.TextIOBase, capture: io.TextIOBase) -> None:
    if stream is None:
        return
    for line in stream:
        capture.write(line)
        target.write(line)
        target.flush()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a command and fail on unclassified warnings/errors in output.')
    parser.add_argument('--cwd')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--ignore-pattern', action='append', default=[])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise SystemExit('No command provided')

    command_cwd = ROOT / args.cwd if args.cwd else ROOT

    proc = subprocess.Popen(
        command,
        cwd=command_cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    with tempfile.TemporaryFile(mode='w+t') as stdout_capture, tempfile.TemporaryFile(mode='w+t') as stderr_capture:
        stdout_thread = threading.Thread(
            target=_pipe_stream,
            args=(proc.stdout, sys.stdout, stdout_capture),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_pipe_stream,
            args=(proc.stderr, sys.stderr, stderr_capture),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        returncode = proc.wait()
        stdout_thread.join()
        stderr_thread.join()

        stdout_capture.seek(0)
        stderr_capture.seek(0)
        match_count = sum(1 for _ in _scan(stdout_capture, stderr_capture, args.ignore_pattern))
        exit_line = f'command exited with code {returncode}'
        report_exit = returncode != 0 and not any(pattern in exit_line for pattern in args.ignore_pattern)
        if report_exit:
            match_count += 1
        if match_count == 0:
            raise SystemExit(returncode)

        print(f'warning scanner found {match_count} unclassified matches', file=sys.stderr)
        stdout_capture.seek(0)
        stderr_capture.seek(0)
        for item in _scan(stdout_capture, stderr_capture, args.ignore_pattern):
            print(f'  line {item.line_number}: [{item.pattern}] {item.line}', file=sys.stderr)
        if report_exit:
            print(f'  line 0: [NONZERO_EXIT] {exit_line}', file=sys.stderr)

        if args.report_only and returncode == 0:
            raise SystemExit(0)

        raise SystemExit(returncode or 1)


if __name__ == '__main__':
    main()

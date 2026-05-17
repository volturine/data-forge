from __future__ import annotations

import argparse
import io
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PATTERNS = [
    "Warning:",
    "Traceback",
    "UnhandledPromiseRejection",
    "DeprecationWarning",
    "ResourceWarning",
    "ERROR",
    "EPIPE",
    "ECONNRESET",
]


@dataclass(frozen=True)
class Match:
    pattern: str
    line_number: int
    line: str


def _scan(output: str) -> list[Match]:
    matches: list[Match] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        for pattern in DEFAULT_PATTERNS:
            if pattern in line:
                matches.append(Match(pattern=pattern, line_number=line_number, line=line))
                break
    return matches


def _pipe_stream(stream: io.TextIOBase | None, target: io.TextIOBase, chunks: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        chunks.append(line)
        target.write(line)
        target.flush()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a command and fail on unclassified warnings/errors in output.")
    parser.add_argument("--cwd")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def _scan_returncode(returncode: int) -> list[Match]:
    if returncode == 0:
        return []
    return [Match(pattern="NONZERO_EXIT", line_number=0, line=f"command exited with code {returncode}")]


def main() -> None:
    args = _parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No command provided")

    command_cwd = ROOT / args.cwd if args.cwd else ROOT

    proc = subprocess.Popen(
        command,
        cwd=command_cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = threading.Thread(
        target=_pipe_stream,
        args=(proc.stdout, sys.stdout, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pipe_stream,
        args=(proc.stderr, sys.stderr, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = proc.wait()
    stdout_thread.join()
    stderr_thread.join()

    combined = "".join(stdout_chunks + stderr_chunks)
    matches = [*_scan(combined), *_scan_returncode(returncode)]
    if not matches:
        raise SystemExit(returncode)

    print(f"warning scanner found {len(matches)} unclassified matches", file=sys.stderr)
    for item in matches:
        print(f"  line {item.line_number}: [{item.pattern}] {item.line}", file=sys.stderr)

    if args.report_only and returncode == 0:
        raise SystemExit(0)

    raise SystemExit(returncode or 1)


if __name__ == "__main__":
    main()

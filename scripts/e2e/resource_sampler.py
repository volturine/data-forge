#!/usr/bin/env python3
"""Collect bounded, run-scoped host and Docker load-probe samples."""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

_SAMPLE_INTERVAL_SECONDS = 2.5
_SAMPLE_BUDGET_SECONDS = 1.5
_STOP = Event()
_ACTIVE_PROCESS: subprocess.Popen[str] | None = None

_HEADER = (
    "timestamp_utc",
    "kind",
    "name",
    "cpu_percent",
    "memory_usage",
    "memory_percent",
    "container_process_count",
    "load_1m",
    "load_5m",
    "load_15m",
    "host_runnable_processes",
    "playwright_processes",
    "playwright_cpu_percent_sum",
    "playwright_rss_kb_sum",
    "playwright_runnable_processes",
    "error",
)


def _stop(_signum: int, _frame: object) -> None:
    _STOP.set()
    process = _ACTIVE_PROCESS
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _bounded_command(command: list[str], deadline: float) -> str:
    global _ACTIVE_PROCESS
    if _STOP.is_set():
        raise TimeoutError("sampler stopping")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("sample budget exhausted")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _ACTIVE_PROCESS = process
    try:
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise TimeoutError(f"{command[0]} timed out") from exc
    finally:
        _ACTIVE_PROCESS = None

    if process.returncode != 0:
        detail = stderr.strip().replace("\t", " ").replace("\n", " ")
        raise RuntimeError(detail[-240:] or f"{command[0]} exited {process.returncode}")
    return stdout


def _load_averages(deadline: float) -> tuple[str, str, str]:
    try:
        if sys.platform == "darwin":
            raw = _bounded_command(["sysctl", "-n", "vm.loadavg"], deadline)
            values = raw.replace("{", " ").replace("}", " ").split()
        else:
            values = Path("/proc/loadavg").read_text().split()[:3]
        if len(values) != 3:
            raise ValueError("load average returned fewer than three values")
        return values[0], values[1], values[2]
    except (OSError, RuntimeError, TimeoutError, ValueError):
        return "", "", ""


def _process_rows(deadline: float) -> list[tuple[int, int, float, int, str, str]]:
    try:
        raw = _bounded_command(
            ["ps", "-axo", "pid=,ppid=,%cpu=,rss=,state=,command="],
            deadline,
        )
    except (OSError, RuntimeError, TimeoutError):
        return []

    rows = []
    for line in raw.splitlines():
        fields = line.strip().split(None, 5)
        if len(fields) != 6:
            continue
        try:
            rows.append((int(fields[0]), int(fields[1]), float(fields[2]), int(fields[3]), fields[4], fields[5]))
        except ValueError:
            continue
    return rows


def _playwright_summary(
    rows: list[tuple[int, int, float, int, str, str]],
    script_pid: int,
) -> tuple[int, float, int, int]:
    descendants: set[int] = set()
    changed = True
    while changed:
        changed = False
        for pid, parent_pid, _cpu, _rss, _state, _command in rows:
            if parent_pid == script_pid or parent_pid in descendants:
                if pid not in descendants:
                    descendants.add(pid)
                    changed = True

    roots = {
        pid
        for pid, _parent_pid, _cpu, _rss, _state, command in rows
        if pid in descendants and "run_with_timeout.py" in command and "tests/concurrency.test.ts" in command
    }
    selected = set(roots)
    changed = True
    while changed:
        changed = False
        for pid, parent_pid, _cpu, _rss, _state, _command in rows:
            if parent_pid in selected and pid not in selected:
                selected.add(pid)
                changed = True

    browser_rows = [row for row in rows if row[0] in selected]
    return (
        len(browser_rows),
        sum(row[2] for row in browser_rows),
        sum(row[3] for row in browser_rows),
        sum(row[4].startswith("R") for row in browser_rows),
    )


def _container_ids(
    compose_project: str,
    deployment_id: str,
    runner_name: str,
    deadline: float,
) -> tuple[list[str], list[str]]:
    # Docker's project and deployment labels are alternatives, so list label
    # metadata once and send only exact run-owned IDs to `docker stats`.
    template = (
        '{{.ID}}\t{{.Names}}\t{{.Label "com.docker.compose.project"}}'
        '\t{{.Label "io.dataforge.deployment"}}'
    )
    try:
        container_rows = _bounded_command(
            ["docker", "ps", "--format", template],
            deadline,
        )
    except (OSError, RuntimeError, TimeoutError) as exc:
        return [], [str(exc)]

    ids = set()
    for line in container_rows.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        container_id, name, project_label, deployment_label = fields
        if project_label == compose_project or deployment_label == deployment_id or name == runner_name:
            ids.add(container_id)
    return sorted(ids), []


def _sample(
    writer: csv.writer,
    compose_project: str,
    deployment_id: str,
    runner_name: str,
    script_pid: int,
) -> None:
    started = time.monotonic()
    deadline = started + _SAMPLE_BUDGET_SECONDS
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    errors: list[str] = []
    process_rows = _process_rows(deadline)
    load_averages = _load_averages(deadline)
    browser_count, browser_cpu, browser_rss, browser_runnable = _playwright_summary(process_rows, script_pid)
    host_runnable = sum(row[4].startswith("R") for row in process_rows)
    ids, docker_errors = _container_ids(compose_project, deployment_id, runner_name, deadline)
    errors.extend(docker_errors)

    container_rows: list[list[str]] = []
    if ids and time.monotonic() < deadline:
        try:
            raw_stats = _bounded_command(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}",
                    *ids,
                ],
                deadline,
            )
            for line in raw_stats.splitlines():
                fields = line.split("\t")
                if len(fields) == 5:
                    container_rows.append(fields)
        except (OSError, RuntimeError, TimeoutError) as exc:
            errors.append(str(exc))
    elif ids:
        errors.append("sample budget exhausted before docker stats")

    writer.writerow(
        (
            timestamp,
            "host",
            "",
            "",
            "",
            "",
            "",
            *load_averages,
            host_runnable,
            browser_count,
            f"{browser_cpu:.1f}",
            browser_rss,
            browser_runnable,
            "; ".join(errors).replace("\t", " "),
        )
    )
    for name, cpu, memory, memory_percent, pids in container_rows:
        writer.writerow(
            (timestamp, "container", name, cpu, memory, memory_percent, pids, "", "", "", "", "", "", "", "", "")
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose_project")
    parser.add_argument("deployment_id")
    parser.add_argument("runner_name")
    parser.add_argument("script_pid", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    with args.output.open("w", newline="") as output_file:
        writer = csv.writer(output_file, delimiter="\t", lineterminator="\n")
        writer.writerow(_HEADER)
        output_file.flush()
        next_sample = time.monotonic()
        while not _STOP.is_set():
            _sample(writer, args.compose_project, args.deployment_id, args.runner_name, args.script_pid)
            output_file.flush()
            next_sample += _SAMPLE_INTERVAL_SECONDS
            if next_sample < time.monotonic():
                next_sample = time.monotonic() + _SAMPLE_INTERVAL_SECONDS
            _STOP.wait(max(0.0, next_sample - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

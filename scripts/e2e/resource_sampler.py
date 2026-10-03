#!/usr/bin/env python3
"""Collect bounded Linux-runner and private-Docker load-probe samples."""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

_SAMPLE_INTERVAL_SECONDS = 5.0
_SAMPLE_BUDGET_SECONDS = 3.0
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
    "runner_process_count",
    "runner_cpu_percent_sum",
    "runner_rss_kb_sum",
    "runner_runnable_processes",
    "runner_cgroup_cpu_usage_usec",
    "runner_cgroup_cpu_user_usec",
    "runner_cgroup_cpu_system_usec",
    "runner_cgroup_memory_current_bytes",
    "runner_cgroup_memory_max_bytes",
    "runner_cgroup_cpu_pressure_some_avg10",
    "runner_cgroup_cpu_pressure_full_avg10",
    "runner_cgroup_memory_pressure_some_avg10",
    "runner_cgroup_memory_pressure_full_avg10",
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
        values = Path("/proc/loadavg").read_text().split()[:3]
        if len(values) != 3:
            raise ValueError("load average returned fewer than three values")
        return values[0], values[1], values[2]
    except OSError, RuntimeError, TimeoutError, ValueError:
        return "", "", ""


def _read_cgroup_key_values(path: Path) -> dict[str, str]:
    try:
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) == 2:
                values[fields[0]] = fields[1]
        return values
    except OSError:
        return {}


def _read_pressure_avg10(path: Path) -> dict[str, str]:
    try:
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            fields = line.split()
            if not fields:
                continue
            for field in fields[1:]:
                key, separator, value = field.partition("=")
                if separator and key == "avg10":
                    values[fields[0]] = value
        return values
    except OSError:
        return {}


def _runner_cgroup_metrics() -> tuple[str, ...]:
    cgroup_root = Path("/sys/fs/cgroup")
    cpu = _read_cgroup_key_values(cgroup_root / "cpu.stat")
    cpu_pressure = _read_pressure_avg10(cgroup_root / "cpu.pressure")
    memory_pressure = _read_pressure_avg10(cgroup_root / "memory.pressure")
    return (
        cpu.get("usage_usec", ""),
        cpu.get("user_usec", ""),
        cpu.get("system_usec", ""),
        _read_scalar(cgroup_root / "memory.current"),
        _read_scalar(cgroup_root / "memory.max"),
        cpu_pressure.get("some", ""),
        cpu_pressure.get("full", ""),
        memory_pressure.get("some", ""),
        memory_pressure.get("full", ""),
    )


def _read_scalar(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _process_rows(deadline: float) -> list[tuple[int, int, float, int, str, str]]:
    try:
        raw = _bounded_command(
            ["ps", "-eo", "pid=,ppid=,%cpu=,rss=,stat=,args="],
            deadline,
        )
    except OSError, RuntimeError, TimeoutError:
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


def _runner_process_summary(
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

    runner_rows = [row for row in rows if row[0] in descendants]
    return (
        len(runner_rows),
        sum(row[2] for row in runner_rows),
        sum(row[3] for row in runner_rows),
        sum(row[4].startswith("R") for row in runner_rows),
    )


def _container_ids(
    compose_project: str,
    deployment_id: str,
    runner_name: str,
    deadline: float,
) -> tuple[list[str], list[str]]:
    # Docker's project and deployment labels are alternatives, so list label
    # metadata once and send only exact run-owned IDs to `docker stats`.
    template = '{{.ID}}\t{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "io.dataforge.deployment"}}'
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
    runner_count, runner_cpu, runner_rss, runner_runnable = _runner_process_summary(process_rows, script_pid)
    runner_cgroup_metrics = _runner_cgroup_metrics()
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
            "runner",
            "",
            "",
            "",
            "",
            "",
            *load_averages,
            runner_count,
            f"{runner_cpu:.1f}",
            runner_rss,
            runner_runnable,
            *runner_cgroup_metrics,
            "; ".join(errors).replace("\t", " "),
        )
    )
    for name, cpu, memory, memory_percent, pids in container_rows:
        writer.writerow(
            (
                timestamp,
                "container",
                name,
                cpu,
                memory,
                memory_percent,
                pids,
                *("",) * (len(_HEADER) - 7),
            )
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

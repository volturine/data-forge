from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _fmt(ms: float) -> str:
    return f"{ms / 1000:7.1f}s"


def _iter_tests(node):
    if isinstance(node, dict):
        for sub in node.get("suites", []):
            yield from _iter_tests(sub)
        for spec in node.get("specs", []):
            file = spec.get("file")
            title = spec.get("title")
            for test in spec.get("tests", []):
                yield file, title, test
    elif isinstance(node, list):
        for item in node:
            yield from _iter_tests(item)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate per-file timing from a Playwright JSON report."
    )
    parser.add_argument(
        "report", type=Path, help="Path to the Playwright JSON reporter output"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="List the slowest tests per file"
    )
    args = parser.parse_args()

    with args.report.open() as fh:
        report = json.load(fh)

    per_file: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    worker_totals: dict[int, float] = defaultdict(float)
    overall_ms = 0.0

    for file, title, test in _iter_tests(report["suites"]):
        if not file:
            continue
        file = Path(file).name
        for result in test["results"]:
            duration = float(result["duration"])
            status = result["status"]
            if status not in ("passed", "failed", "timedOut", "interrupted"):
                continue
            # workerIndex changes when Playwright replaces a worker process;
            # parallelIndex is the stable execution slot and therefore the
            # correct unit for estimating the wall-clock critical path.
            parallel_index = result.get("parallelIndex", result["workerIndex"])
            per_file[file].append((title, duration, parallel_index))
            worker_totals[parallel_index] += duration
            overall_ms += duration

    print(f"Total tests measured: {sum(len(v) for v in per_file.values())}")
    print(f"Sum of test durations: {_fmt(overall_ms)}")
    print(
        f"Longest worker critical path: {_fmt(max(worker_totals.values(), default=0.0))} "
        f"(lower bound on wall-clock, {len(worker_totals)} workers)"
    )
    print()

    ranked = sorted(
        per_file.items(), key=lambda kv: sum(d for _, d, _ in kv[1]), reverse=True
    )

    print(
        f"{'file':<26} {'count':>5} {'total':>9} {'mean':>9} {'median':>9} {'p90':>9} {'slowest':>9}"
    )
    print("-" * 78)
    for file, entries in ranked:
        durations = [d for _, d, _ in entries]
        total = sum(durations)
        slowest_title, slowest_ms, _ = max(entries, key=lambda e: e[1])
        p90 = (
            statistics.quantiles(durations, n=10, method="inclusive")[8]
            if len(durations) >= 2
            else durations[0]
        )
        print(
            f"{file:<26} {len(durations):>5} {_fmt(total):>9} {_fmt(statistics.mean(durations)):>9} "
            f"{_fmt(statistics.median(durations)):>9} {_fmt(p90):>9} {_fmt(slowest_ms):>9}"
        )
        if args.verbose:
            for title, ms, _ in sorted(entries, key=lambda e: e[1], reverse=True)[:5]:
                print(f"    {_fmt(ms)}  {title[:90]}")

    print()
    print("Worker load:")
    for worker, total in sorted(worker_totals.items()):
        print(f"  worker {worker}: {_fmt(total)}")


if __name__ == "__main__":
    main()

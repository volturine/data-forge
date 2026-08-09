from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

UUID_RE = re.compile(r'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


def _endpoint(url: str) -> str:
    path = urlsplit(url).path.rstrip('/') or '/'
    return '/'.join(':id' if UUID_RE.fullmatch(part) else part for part in path.split('/'))


def _fmt(ms: float) -> str:
    return f'{ms / 1000:7.1f}s'


def main() -> None:
    parser = argparse.ArgumentParser(description='Aggregate API request traces captured by tests/utils/request-trace.ts.')
    parser.add_argument('dir', type=Path, help='PLAYWRIGHT_REQUEST_TRACE_DIR output')
    parser.add_argument('--endpoints', action='store_true', help='Per-endpoint counts/timing across all tests')
    parser.add_argument('--tests', action='store_true', help='Per-test request composition')
    parser.add_argument(
        '--occupancy',
        action='store_true',
        help='Compute-request concurrency across all traced browser workers',
    )
    parser.add_argument('--top', type=int, default=25, help='How many rows to show')
    parser.add_argument(
        '--url-pattern',
        help='Only include entries whose URL matches this substring (e.g. /compute/preview)',
    )
    args = parser.parse_args()

    entries = []
    for file in sorted(args.dir.glob('*.jsonl')):
        for line in file.read_text().splitlines():
            if not line.strip():
                continue
            entries.append(json.loads(line))

    completed = [e for e in entries if e.get('durationMs') is not None]

    if args.url_pattern:
        entries = [e for e in entries if args.url_pattern in e['url']]

    print(f'Total requests recorded: {len(entries)} ({len(completed)} completed, {len(entries) - len(completed)} unfinished)')

    if args.endpoints:
        by_endpoint: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
        for e in completed:
            endpoint = f'{e["method"]} {_endpoint(e["url"])}'
            by_endpoint[endpoint].append((e.get('status') or 0, float(e['durationMs']), e['workerIndex']))
        print(f'\n{"endpoint":<70} {"count":>6} {"mean":>9} {"median":>9} {"p90":>9} {"max":>9}')
        print('-' * 115)
        ranked = sorted(by_endpoint.items(), key=lambda kv: sum(d for _, d, _ in kv[1]), reverse=True)
        for endpoint, data in ranked[: args.top]:
            durations = [d for _, d, _ in data]
            p90 = statistics.quantiles(durations, n=10, method='inclusive')[8] if len(durations) >= 2 else durations[0]
            print(
                f'{endpoint:<70} {len(durations):>6} {_fmt(statistics.mean(durations)):>9} '
                f'{_fmt(statistics.median(durations)):>9} {_fmt(p90):>9} {_fmt(max(durations)):>9}'
            )

    if args.tests:
        by_test: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
        for e in completed:
            by_test[e['title']].append((e['url'], e.get('durationMs') or 0, e.get('status') or 0))
        print(f'\n{"test":<72} {"reqs":>5} {"total":>9} {"mean":>9} {"max":>9}')
        print('-' * 110)
        ranked = sorted(by_test.items(), key=lambda kv: sum(d for _, d, _ in kv[1]), reverse=True)
        for title, data in ranked[: args.top]:
            durations = [d for _, d, _ in data]
            print(f'{title[:72]:<72} {len(durations):>5} {_fmt(sum(durations)):>9} {_fmt(statistics.mean(durations)):>9} {_fmt(max(durations)):>9}')

    if args.occupancy:
        compute_entries = [e for e in completed if '/api/v1/compute/' in e['url'] and e.get('startEpochMs') is not None and e.get('endEpochMs') is not None]
        events = sorted(
            [(float(e['startEpochMs']), 1) for e in compute_entries] + [(float(e['endEpochMs']), -1) for e in compute_entries],
            key=lambda event: (event[0], event[1]),
        )
        concurrency_ms: dict[int, float] = defaultdict(float)
        active = 0
        peak = 0
        previous: float | None = None
        for timestamp, delta in events:
            if previous is not None and timestamp > previous:
                concurrency_ms[active] += timestamp - previous
            active += delta
            peak = max(peak, active)
            previous = timestamp
        observed_ms = sum(concurrency_ms.values())
        busy_ms = observed_ms - concurrency_ms.get(0, 0.0)
        request_ms = sum(float(e['durationMs']) for e in compute_entries)
        print('\nCompute request occupancy:')
        print(f'  requests: {len(compute_entries)}')
        print(f'  observed window: {_fmt(observed_ms)}')
        print(f'  busy with at least one request: {_fmt(busy_ms)}')
        print(f'  aggregate request time: {_fmt(request_ms)}')
        print(f'  peak concurrent requests: {peak}')
        if observed_ms:
            print(f'  mean concurrency: {request_ms / observed_ms:.2f}')
        for concurrency, duration in sorted(concurrency_ms.items()):
            if concurrency == 0 or duration <= 0:
                continue
            print(f'  time at concurrency {concurrency}: {_fmt(duration)}')

    if not args.endpoints and not args.tests and not args.occupancy:
        print('Pass --endpoints, --tests, and/or --occupancy to aggregate.')


if __name__ == '__main__':
    main()

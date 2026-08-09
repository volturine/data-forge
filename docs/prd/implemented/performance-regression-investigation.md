# Performance regression investigation

> **Status (audited 2026-08-09): Implemented — regression attributed, optimized baseline accepted, warning gate clean.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-09_

The performance investigation opened against the 445.91s five-run mean is
complete. Its measured revision has a 410.93s mean: 34.98s / 7.85% faster, with
all 353 tests passing in five consecutive runs and zero retries. The temporary
production-wide S3-client workaround was rejected and reverted. Explicit bucket
provisioning now removes the empty marker upload that triggered botocore's stale
`Expect: 100-continue` connection state.

## Acceptance decision

The acceptance threshold for this cycle was fixed before evaluating the final
five-run mean:

- five consecutive canonical `just test-e2e` runs with 353/353 passing;
- zero retries and zero unclassified warnings;
- mean command wall-clock at least 5% below the prior 445.91s mean
  (at most 423.61s); and
- no individual run slower than the prior 445.91s mean.

The measured performance revision met every timing condition: mean 410.93s,
worst 422.95s. The remaining 41.9% gap to the May 289.55s historical mean is
accepted as the current product baseline. Direct traces show that the dominant
work is real, visible compute and datasource behavior; removing it would weaken
the product or coverage. Future performance work starts from 410.93s and must
optimize those product operations, not test waits.

The checksum and botocore handler changes used during the five-run measurement
have been fully reverted rather than retained as production-wide compatibility
behavior. The final revision meets the warning condition through the scoped
namespace-provisioning fix.

## Replacement five-run baseline

Environment: Apple M4 (10 logical CPUs, 24 GiB RAM), macOS/Darwin arm64,
Docker 29.5.2, Bun 1.3.11, Python 3.14.2, four Playwright workers,
`fullyParallel: false`, `retries: 0`.

Command for every run:

```bash
PW_E2E_WORKERS=4 /usr/bin/time -p just test-e2e
```

| Run | Result | Command wall-clock |
| --- | ---: | ---: |
| 1 | 353 passed | 422.95s |
| 2 | 353 passed | 402.38s |
| 3 | 353 passed | 417.79s |
| 4 | 353 passed | 407.33s |
| 5 | 353 passed | 404.18s |

- Mean: **410.93s**
- Median: **407.33s**
- Best: **402.38s**
- Worst: **422.95s**
- Range: **20.57s**
- Prior mean: **445.91s**
- Improvement: **34.98s / 7.85%**

The corresponding sums of Playwright test durations were 1458.2s, 1409.5s,
1437.9s, 1394.9s, and 1387.4s. The stable four-worker critical-path lower
bounds were 382.2s, 370.9s, 378.6s, 366.7s, and 362.7s. These values are
reproducible with `scripts/analyze_e2e_profile.py` and the opt-in JSON reporter.

These timings were recorded before the unsafe S3-client experiment was
reverted. They remain the accepted performance measurement, but they are not
evidence that the current RustFS configuration passes the warning gate.

## RustFS `1.0.0-rc.1` validation

All repository launch points now use `rustfs/rustfs:1.0.0-rc.1`, resolved during
validation to digest
`sha256:f53d700fc16809070326f6ab3fb565d48e722364a7bd5a12e47d0a5abe079ce6`.
The production S3 client retains its normal botocore checksum and event-handler
behavior.

Two four-worker E2E runs reproduced the original issue:

| Scope | Browser result | RustFS/urllib3 result |
| --- | ---: | --- |
| upload-heavy 104-test subset | 104 passed in 3.5m | warning gate failed; 5 malformed-response tracebacks |
| complete suite | 353 passed in 7.2m | 4 malformed-response tracebacks in the worker log |

An in-line raw TCP capture corrected the initial parser-level interpretation.
RustFS sends a valid final `200 OK` for an empty `.namespace-root` PUT instead
of `100 Continue`, which HTTP permits. Botocore stores that early final status
in its connection response class. Because the following CSV PUT also carries
`Expect: 100-continue`, botocore reuses the stale response class after consuming
the CSV request's real `100 Continue`; urllib3 then interprets the CSV's real
`200 OK` status line as malformed headers and emits
`MissingHeaderBodySeparatorDefect`.

The trigger was introduced by namespace provisioning, which uploads an empty
`.namespace-root` marker immediately before normal uploads on a persistent S3
connection. A standalone reproduction using only boto3 and RustFS produces one
warning per empty-marker/non-empty-upload pair; `1.0.0-rc.1` can instead time
out on the same sequence. Both a non-empty marker and botocore's targeted
`BOTO_EXPERIMENTAL__NO_EMPTY_CONTINUE=true` behavior eliminate the reproduction.
Pinning `1.0.0-rc.1` alone therefore does not resolve the client-state defect.

The implemented resolution adds an explicit `EnsureBucket` data-plane RPC and
uses the worker's existing `ensure_bucket_exists()` operation. Namespace
creation no longer uploads `.namespace-root` or any other marker object. The
original namespace-isolation reproduction passes 5/5 with a clean warning scan,
and the canonical four-worker suite passes 353/353 in 6.6 minutes with no
RustFS/urllib3 header warning.

## Direct attribution evidence

The final full-suite profiling run used:

```bash
PW_E2E_WORKERS=4 \
PLAYWRIGHT_REQUEST_TRACE_DIR=.tmp-request-trace-clean-1b \
PLAYWRIGHT_JSON_REPORT=.tmp-full-clean-1b.json \
just test-e2e
python3 scripts/analyze_request_trace.py \
  .tmp-request-trace-clean-1b --endpoints --tests --occupancy
```

It recorded 5,204 browser API requests: 4,818 completed before page teardown
and 386 intentionally unfinished during teardown/navigation. Ranked compute
evidence:

| Path | Count | Mean | Median | p90 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `POST /compute/preview` | 185 | 1.6s | 1.5s | 2.8s | 3.9s |
| `POST /compute/schema` | 16 | 1.8s | 1.7s | 2.5s | 2.9s |
| `POST /compute/row-count` | 3 | 3.2s | 3.2s | 3.4s | 3.5s |
| `DELETE /compute/engine/analysis/:id` | 37 | 1.0s | 0.9s | 1.6s | 2.0s |

Compute requests occupied 226.5s of the 384.5s browser window. Aggregate
request time was 463.4s, mean concurrency 1.21, and peak concurrency 8. Only
11.2s were spent above concurrency four. Therefore configured request-worker
capacity is not the bottleneck and visible builds are not starved by preview
traffic. The measured owner is the actual preview/schema/row-count work in
`compute_request_runtime.py` and its per-analysis engines.

The 170-test target-file run independently ranked the cost in
`analysis-pipeline`, `analysis-operations`, `analysis-editor`, and
`analysis-output`. `profile` remained cheap, while namespace switching cost
was dominated by correct remount/refetch behavior. Request inspection found
one preview per visible inline-preview mount or explicit pipeline change; it
did not find overlapping identical requests that could be removed safely.

## Implemented changes

- Replaced retry loops, fixed sleeps, and backend/network-coupled waits with
  direct Playwright locator assertions while preserving visible coverage.
- Added background build-history refresh without blanking existing rows, with
  focused store regression tests.
- Added opt-in collision-safe request traces with endpoint, target-step,
  timing, failure, and cross-worker occupancy data.
- Fixed profiling aggregation for single-test files and stable Playwright
  parallel slots.
- Pinned development, Docker Compose, backend harness, and E2E RustFS launches
  to `1.0.0-rc.1` without changing production botocore behavior.
- Replaced empty namespace marker uploads with an explicit worker-owned
  `EnsureBucket` data-plane operation.

## Exit criteria

- [x] Direct timing, occupancy, and request-count evidence is recorded.
- [x] Implemented optimizations have focused regression coverage.
- [x] `just verify` and `just test` pass on the final revision.
- [x] The final revision passes `just test-e2e` without unclassified warnings.
- [x] The replacement baseline and comparison are published.
- [x] The documented acceptance threshold is met.

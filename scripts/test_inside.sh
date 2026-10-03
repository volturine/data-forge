#!/usr/bin/env bash
set -euo pipefail

cd /app
mkdir -p .test-artifacts
log_file="/app/.test-artifacts/test.log"
exec > >(tee -a "$log_file") 2>&1

LOCAL_SERVICE_HOST="$(ip -4 -o addr show dev eth0 | awk '{split($4, address, "/"); print address[1]; exit}')"
if [ -z "$LOCAL_SERVICE_HOST" ]; then
    echo 'Could not determine the test runner container IPv4 address.' >&2
    exit 1
fi
export LOCAL_SERVICE_HOST
export TEST_PROCESS_HOST="$LOCAL_SERVICE_HOST"
export TEST_DOCKER_SERVICE_HOST=docker

docker info --format \
    'CgroupVersion={{.CgroupVersion}} CgroupDriver={{.CgroupDriver}} MemoryBytes={{.MemTotal}} CPUs={{.NCPU}}' \
    > /app/.test-artifacts/nested-docker-info.txt
python - "$TEST_OUTER_NETWORK_SUBNETS" "$INNER_DOCKER_BRIDGE" "$INNER_DOCKER_ADDRESS_POOL" \
    > /app/.test-artifacts/docker-network-cidrs.txt <<'PY'
from ipaddress import ip_network
import sys

outer = [ip_network(cidr, strict=False) for cidr in sys.argv[1].split(',') if cidr]
inner = [ip_network(sys.argv[2], strict=False), ip_network(sys.argv[3], strict=False)]
if not outer:
    raise SystemExit('No outer Compose network CIDR was provided for the overlap check')
overlaps = [(outer_cidr, inner_cidr) for outer_cidr in outer for inner_cidr in inner if outer_cidr.overlaps(inner_cidr)]
if overlaps:
    for outer_cidr, inner_cidr in overlaps:
        print(f'CIDR overlap: outer {outer_cidr} conflicts with inner {inner_cidr}', file=sys.stderr)
    raise SystemExit(2)

print(f'outer={",".join(map(str, outer))}')
print(f'inner={",".join(map(str, inner))}')
PY
{
    cat /proc/self/cgroup
    for cgroup_file in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.events /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
        if [ -r "$cgroup_file" ]; then
            printf '%s=' "$cgroup_file"
            cat "$cgroup_file"
        fi
    done
} > /app/.test-artifacts/runner-cgroup.txt

docker events --filter type=container --filter event=oom --format '{{json .}}' \
    > /app/.test-artifacts/nested-docker-oom-events.jsonl 2>&1 &
oom_event_pid=$!
stop_oom_capture() {
    kill "$oom_event_pid" 2>/dev/null || true
    wait "$oom_event_pid" 2>/dev/null || true
}
trap stop_oom_capture EXIT

target="${TEST_TARGET:-${1:-}}"
case "$target" in
    test-backend-unit) raw_target=test-backend-unit-raw ;;
    test-backend-integration) raw_target=test-backend-integration-raw ;;
    test-worker) raw_target=test-worker-raw ;;
    test-scheduler) raw_target=test-scheduler-raw ;;
    test-frontend) raw_target=test-frontend-raw ;;
    test-runtime-stability)
        raw_target=test-runtime-stability-raw
        ;;
    test-e2e)
        raw_target=test-e2e-raw
        ;;
    test-e2e-capacity)
        raw_target=test-e2e-capacity-raw
        ;;
    *)
        echo "Unknown test target: ${target}" >&2
        exit 2
        ;;
esac

scanner=(uv run --project /app/packages/backend python /app/scripts/scan_warnings.py)
if [ "$target" = test-e2e ] || [ "$target" = test-e2e-capacity ]; then
    scanner+=(--ignore-pattern 'InvalidCredentialsError: Invalid email or password')
    # The permanent load probe deliberately creates 30 cold analysis workers.
    # Keep its successful-completion latency records visible in test.log, but
    # don't treat those structured measurements as application warnings.
    scanner+=(
        --ignore-pattern 'Slow internal runtime RPC method='
        --ignore-pattern 'Slow API request phase=in_flight method=POST path=/api/v1/compute/preview'
        --ignore-pattern 'Slow API request phase=completed method=POST path=/api/v1/compute/preview status=200'
        --ignore-pattern 'Compute request still waiting durable_request_id='
        --ignore-pattern 'Slow compute response signal wait request_id='
        --ignore-pattern 'Compute response waiter woke durable_request_id='
    )
fi
scanner+=(-- just "$raw_target")
if [ "$target" = test-runtime-stability ]; then
    scanner+=("${REPEATS:-3}")
fi
"${scanner[@]}"

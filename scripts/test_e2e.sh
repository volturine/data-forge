#!/usr/bin/env bash
# E2E harness for the fully containerized stack.
#
# Exactly one app stack (postgres, rustfs, api, scheduler, worker) exists per
# run; the only thing that scales is Playwright: E2E_SHARDS runner containers
# run in parallel, each with PW_E2E_WORKERS browser workers, all sharing the
# one app over the private Docker network. Nothing is published to the host.
#
# Usage:
#   test_e2e.sh              # stack up, parallel Playwright shards, stack down
#   test_e2e.sh stack-down   # stop and remove a leftover stack
set -euo pipefail
set -a; source docker/env/e2e.env; set +a
# Playwright forces FORCE_COLOR=1 for worker processes, so drop NO_COLOR to
# keep the warning scanner clean and avoid conflicting color policies.
unset NO_COLOR
unset VIRTUAL_ENV

ROOT_DIR="$(pwd)"
PLAYWRIGHT_ARTIFACTS_DIR="${ROOT_DIR}/packages/frontend/tests/.artifacts/playwright"
LOG_DIR="${E2E_LOG_DIR:-}"

# Fixed names: leftover stacks from aborted runs can be removed with stack-down.
E2E_DOCKER_NETWORK="dataforge-e2e-net"
E2E_DEPLOYMENT_ID="dataforge-e2e"
export E2E_DOCKER_NETWORK E2E_DEPLOYMENT_ID
COMPOSE=(docker compose -p dataforge-e2e -f docker/compose.e2e.yaml)

ENGINE_IMAGE="data-forge-polars-engine:e2e"

PLAYWRIGHT_VERSION="$(node -p "require('./packages/frontend/node_modules/playwright/package.json').version")"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble"

build_images() {
    echo "Building e2e images"
    for target in api scheduler worker; do
        # BuildKit layer cache keeps rebuilds cheap when a target is unchanged.
        DOCKER_BUILDKIT=1 docker build -q -f docker/Dockerfile --target "$target" -t "data-forge-${target}:e2e" . >/dev/null
    done
    DOCKER_BUILDKIT=1 docker build -q -f docker/Dockerfile --target engine -t "${ENGINE_IMAGE}" . >/dev/null
}

resolve_docker_socket_gid() {
    # The gid the worker needs is the one *containers* see: on Docker Desktop
    # the daemon runs in a VM where the socket is root-owned, which does not
    # match the host inode. Ask a container instead of stat-ing the host.
    DOCKER_SOCKET_GID="$(docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
        --entrypoint stat "data-forge-worker:e2e" -c %g /var/run/docker.sock)"
    export DOCKER_SOCKET_GID
}

stack_up() {
    build_images
    resolve_docker_socket_gid
    echo "Starting e2e stack (postgres, rustfs, api, scheduler, worker)"
    if ! "${COMPOSE[@]}" up -d --wait; then
        echo "E2E stack failed readiness; capturing service logs" >&2
        dump_service_logs
        return 1
    fi
    echo "E2E stack is ready"
}

stack_down() {
    # Stop services first so the worker cannot spawn engines during teardown,
    # then sweep the spawned engines (label filter) both before and after: an
    # engine claimed in the race window would otherwise leak past `down -v`.
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-playwright-shard" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" stop >/dev/null 2>&1 || true
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    docker network rm "${E2E_DOCKER_NETWORK}" >/dev/null 2>&1 || true
}

dump_service_logs() {
    if [ -z "$LOG_DIR" ] || [ ! -d "$LOG_DIR" ]; then
        return
    fi
    local service
    for service in api scheduler worker; do
        "${COMPOSE[@]}" logs --no-color "$service" >"$LOG_DIR/${service}.log" 2>&1 || true
    done
    # Engine container stderr/stdout: job tracebacks (datasource load errors,
    # engine-side crashes) only surface here, never in the worker service log.
    docker ps -a --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" --format '{{.Names}}' \
        | while read -r engine_name; do
            docker logs --timestamps "$engine_name" >"${LOG_DIR}/engine-${engine_name}.log" 2>&1 || true
        done
    echo "::group::service log tails"
    for service in api scheduler worker; do
        echo "--- ${service} ---"
        tail -n 100 "$LOG_DIR/${service}.log" || true
    done
    echo "::endgroup::"
}

dump_slow_requests() {
    if [ -z "$LOG_DIR" ] || [ ! -d "$LOG_DIR" ]; then
        return
    fi
    "${COMPOSE[@]}" exec -T postgres psql -U dataforge -d dataforge -c \
        "SELECT round(duration_ms::numeric) AS ms, status, method, path, to_char(ts, 'HH24:MI:SS') AS at
         FROM request_logs
         WHERE duration_ms > 5000 AND ts > now() - interval '3 hours'
         ORDER BY duration_ms DESC LIMIT 40;" \
        >"$LOG_DIR/slow-requests.log" 2>&1 || true
}

wait_for_runtime_drain() {
    echo "Waiting for e2e runtime work to drain"
    # Let ordinary asynchronous work finish, but do not let a request orphaned
    # by a destructive navigation test dominate the local suite runtime.
    local runtime_schema="${DEFAULT_NAMESPACE:-default}"
    if [[ ! "$runtime_schema" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo "Invalid DEFAULT_NAMESPACE for runtime drain query: ${runtime_schema}" >&2
        return 1
    fi
    local deadline=$((SECONDS + 15))
    while true; do
        local active_runtime_work
        active_runtime_work="$(
            "${COMPOSE[@]}" exec -T postgres psql -U dataforge -d dataforge -Atc \
                "SELECT
                    (SELECT count(*) FROM \"${runtime_schema}\".compute_requests WHERE status IN (1, 2)) +
                    (SELECT count(*) FROM \"${runtime_schema}\".build_jobs WHERE status IN ('queued', 'leased', 'running'));" \
                2>/dev/null || echo 1
        )"
        active_runtime_work="${active_runtime_work//$'\n'/}"
        if [ "${active_runtime_work:-1}" -eq 0 ]; then
            break
        fi
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "E2E runtime drain deadline reached (${active_runtime_work} active); proceeding with cooperative shutdown"
            break
        fi
        sleep 1
    done
    # A cancelled build can be terminal in Postgres while its executor is still
    # unwinding the engine RPC. Let that cooperative path finish before signals.
    sleep 2
}

run_playwright_shard() {
    local shard_index="$1"
    local shard_total="$2"
    cd "${ROOT_DIR}/packages/frontend"
    # Playwright wipes its output directory on start, so shards that share one
    # directory delete each other's artifacts mid-run.
    local output_dir="$PWD/tests/.artifacts/playwright/test-results/shard${shard_index}"
    local report_dir="$PWD/tests/.artifacts/playwright/playwright-report/shard${shard_index}"
    local timeout_seconds="${E2E_TIMEOUT_SECONDS:-0}"
    if [ "$timeout_seconds" -eq 0 ]; then
        timeout_seconds=3600
    fi
    mkdir -p "$output_dir" "$report_dir"
    # Optional profiling subset, e.g. PLAYWRIGHT_TEST_FILES="tests/profile.test.ts".
    local test_files=()
    if [ -n "${PLAYWRIGHT_TEST_FILES:-}" ]; then
        read -r -a test_files <<<"${PLAYWRIGHT_TEST_FILES}"
        echo "Running Playwright subset: ${test_files[*]}"
    fi
    local grep_args=()
    if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
        grep_args=(--grep "${PLAYWRIGHT_GREP}")
        echo "Playwright grep: ${PLAYWRIGHT_GREP}"
    fi
    echo "Starting Playwright shard ${shard_index}/${shard_total} (${PW_E2E_WORKERS} browser workers)"
    local trace_args=()
    if [ -n "${PLAYWRIGHT_REQUEST_TRACE_DIR:-}" ]; then
        trace_args=(-e PLAYWRIGHT_REQUEST_TRACE_DIR=/work/.reqtrace/shard${shard_index})
    fi
    python3 "${ROOT_DIR}/scripts/run_with_timeout.py" \
        --timeout-seconds "$timeout_seconds" \
        --grace-seconds "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        -- docker run --rm --init \
            --name "dataforge-e2e-playwright-shard${shard_index}" \
            --network "${E2E_DOCKER_NETWORK}" \
            -v "${ROOT_DIR}:/work" \
            -w /work/packages/frontend \
            -e PW_E2E_WORKERS \
            -e PLAYWRIGHT_BASE_URL=http://api:8000 \
            ${trace_args[@]+"${trace_args[@]}"} \
            -e PLAYWRIGHT_OUTPUT_DIR=/work/packages/frontend/tests/.artifacts/playwright/test-results/shard${shard_index} \
            -e PLAYWRIGHT_HTML_OUTPUT_DIR=/work/packages/frontend/tests/.artifacts/playwright/playwright-report/shard${shard_index} \
            -e CI \
            -e PLAYWRIGHT_JSON_REPORT \
            "${PLAYWRIGHT_IMAGE}" \
            ./node_modules/.bin/playwright test --config=playwright.config.ts \
            --shard="${shard_index}/${shard_total}" \
            ${test_files[@]+"${test_files[@]}"} \
            ${grep_args[@]+"${grep_args[@]}"}
}

action="${1:-all}"
case "$action" in
    all)
        keep_stack="${E2E_KEEP_STACK:-0}"
        cleanup() {
            status=$?
            if [ "$keep_stack" != "1" ]; then
                stack_down
            else
                echo "E2E_KEEP_STACK=1: leaving the stack running for inspection"
            fi
            exit "$status"
        }
        trap cleanup EXIT
        if [ -n "$LOG_DIR" ]; then
            mkdir -p "$LOG_DIR"
        fi
        stack_up

        shards="${E2E_SHARDS:-2}"
        # Leftovers from an aborted run are root-owned (runner containers run
        # as root); hand them back before wiping, then recreate clean.
        docker run --rm --network none -v "${ROOT_DIR}:/work" --entrypoint sh \
            "${PLAYWRIGHT_IMAGE}" -c "chown -R $(id -u):$(id -g) /work/packages/frontend/tests/.artifacts" >/dev/null 2>&1 || true
        rm -rf "${PLAYWRIGHT_ARTIFACTS_DIR}"
        for shard in $(seq 1 "${E2E_SHARDS:-2}"); do
            mkdir -p "${PLAYWRIGHT_ARTIFACTS_DIR}/test-results/shard${shard}" "${PLAYWRIGHT_ARTIFACTS_DIR}/playwright-report/shard${shard}"
        done
        echo "Running ${shards} Playwright shard container(s), ${PW_E2E_WORKERS} browser workers each"
        pids=()
        set +e
        for shard in $(seq 1 "$shards"); do
            run_playwright_shard "$shard" "$shards" &
            pids+=($!)
        done
        failed=0
        for pid in "${pids[@]}"; do
            wait "$pid" || failed=1
        done
        set -e
        # The runner containers write artifacts as root; hand them back to the host user.
        docker run --rm --network none -v "${ROOT_DIR}:/work" --entrypoint sh \
            "${PLAYWRIGHT_IMAGE}" -c "chown -R $(id -u):$(id -g) /work/packages/frontend/tests/.artifacts" >/dev/null 2>&1 || true
        if [ "$failed" -ne 0 ]; then
            dump_service_logs
        fi
        wait_for_runtime_drain
        dump_slow_requests
        exit "$failed"
        ;;
    stack-down)
        stack_down
        ;;
    *)
        echo "usage: test_e2e.sh [all|stack-down]" >&2
        exit 1
        ;;
esac

#!/usr/bin/env bash
# E2E harness for the containerized application stack.
#
# Exactly one app stack (postgres, rustfs, api, runtime, worker, scheduler) exists per
# run. Playwright runs in bounded Linux containers on the same private Docker network.
# The 50-tab probe has its own runner and spreads pages across Chromium processes.
#
# The outer test runner owns the daemon lifecycle; this script always removes its stack.
set -euo pipefail
if [[ "${DATAFORGE_TEST_CONTAINER:-}" != "1" || "${DOCKER_HOST:-}" != "tcp://docker:2375" ]]; then
    echo "Run E2E through the containerized runner (DATAFORGE_TEST_CONTAINER=1, DOCKER_HOST=tcp://docker:2375)." >&2
    exit 2
fi
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; source "${ROOT_DIR}/docker/env/e2e.env"; set +a
source "${ROOT_DIR}/scripts/e2e/test_selection.sh"
E2E_PLAYWRIGHT_BASE_URL="http://api:8000"
E2E_OPENAI_FIXTURE_URL="http://openai-fixture:8001/v1"
# Just passes `browsers=50` as a positional recipe argument when callers use
# the documented `just test-e2e-concurrency browsers=50` form. Accept that
# spelling here as well as the plain environment value.
if [[ "${E2E_CONCURRENCY_BROWSERS:-}" == browsers=* ]]; then
    E2E_CONCURRENCY_BROWSERS="${E2E_CONCURRENCY_BROWSERS#browsers=}"
    export E2E_CONCURRENCY_BROWSERS
fi
# Playwright forces FORCE_COLOR=1 for worker processes, so drop NO_COLOR to
# keep the warning scanner clean and avoid conflicting color policies.
unset NO_COLOR
unset VIRTUAL_ENV

if [[ -n "${E2E_ARTIFACTS_DIR:-}" && "${E2E_ARTIFACTS_DIR}" != /* ]]; then
    E2E_ARTIFACTS_DIR="${ROOT_DIR}/${E2E_ARTIFACTS_DIR}"
fi
if [[ -z "${E2E_STACK_ID:-}" ]]; then
    E2E_STACK_ID="run-$(date +%Y%m%d%H%M%S)-$$"
fi
if [[ ! "${E2E_STACK_ID}" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ ]]; then
    echo "E2E_STACK_ID must be 1-32 lowercase letters, digits, underscores, or hyphens, starting with a letter or digit" >&2
    exit 2
fi
E2E_ARTIFACTS_DIR="${E2E_ARTIFACTS_DIR:-${ROOT_DIR}/.test-artifacts/e2e/${E2E_STACK_ID}}"
E2E_ARTIFACTS_CONTAINER_DIR="${E2E_ARTIFACTS_CONTAINER_DIR:-/work/.test-artifacts/e2e/${E2E_STACK_ID}}"
LOG_DIR="${E2E_LOG_DIR:-${E2E_ARTIFACTS_DIR}/logs}"
if [[ -n "${LOG_DIR}" && "${LOG_DIR}" != /* ]]; then
    LOG_DIR="${ROOT_DIR}/${LOG_DIR}"
fi
PLAYWRIGHT_SHARD_ARTIFACTS_DIR="${E2E_ARTIFACTS_DIR}/playwright-shards"

# Shared fixture datasets are created once for the whole run. Each shard still
# receives its own E2E_RUN_STAMP for user identities and mutable test names,
# while E2E_GLOBAL_RUN_STAMP is the rendezvous key for immutable datasets.
if [ -z "${E2E_GLOBAL_RUN_STAMP:-}" ]; then
    E2E_GLOBAL_RUN_STAMP="${E2E_RUN_STAMP:-e2e-$(date +%s)-$$}"
    export E2E_GLOBAL_RUN_STAMP
fi

# Every run owns a separate compose project, network, volume set, and engine
# label. This lets concurrent E2E runs coexist and prevents test cleanup from
# deleting another run's live database or artifacts.
E2E_DOCKER_NETWORK="dataforge-e2e-${E2E_STACK_ID}-net"
E2E_DEPLOYMENT_ID="dataforge-e2e-${E2E_STACK_ID}"
export E2E_DOCKER_NETWORK E2E_DEPLOYMENT_ID
COMPOSE=(docker compose -p "dataforge-e2e-${E2E_STACK_ID}" -f "${ROOT_DIR}/docker/compose.e2e.yaml")

ENGINE_IMAGE="data-forge-polars-engine:e2e"
WORKER_IMAGE="data-forge-worker:e2e"
ARCHITECTURE_TEST_FILES=(
    tests/runtime-architecture.test.ts
    tests/datasource-compute-isolation.test.ts
)

NORMAL_TEST_FILES=()
NORMAL_GREP_ARGS=()
RUN_CONCURRENCY_PROBE=0
RUN_ARCHITECTURE_TESTS=0
DB_ACTIVITY_SAMPLER_PID=""
LOAD_PROBE_RESOURCE_SAMPLER_PID=""

PLAYWRIGHT_VERSION="$(node -p "require('./packages/frontend/node_modules/playwright/package.json').version")"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble"

playwright_artifacts_root() {
    printf '%s' "${E2E_ARTIFACTS_CONTAINER_DIR}"
}

run_playwright() {
    local timeout_seconds="$1"
    local grace_seconds="$2"
    local runner_name="$3"
    local cpu_limit=""
    shift 3
    local env_args=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
        if [ "$1" = "--cpu-limit" ]; then
            if [ "$#" -lt 2 ]; then
                echo "run_playwright --cpu-limit requires a value" >&2
                return 2
            fi
            cpu_limit="$2"
            shift 2
        else
            env_args+=("$1")
            shift
        fi
    done
    if [ "$#" -eq 0 ]; then
        echo "run_playwright requires '--' before Playwright arguments" >&2
        return 2
    fi
    shift
    local playwright_command=(./node_modules/.bin/playwright test --config=playwright.config.ts)
    if [ "$#" -gt 0 ]; then
        playwright_command+=("$@")
    fi
    local runner_command=(
        docker run --init --shm-size=1gb
        --pids-limit=4096
        --group-add "${DOCKER_SOCKET_GID}"
        --name "$runner_name"
        --network "$E2E_DOCKER_NETWORK"
        -v "${ROOT_DIR}:/work"
        # Bind sources resolve in the private dind container, not on the host.
        -v /usr/local/bin/docker:/usr/local/bin/docker:ro
        -v /var/run/docker.sock:/var/run/docker.sock
        -w /work/packages/frontend
        -e "CI=true"
        -e "DOCKER_HOST=unix:///var/run/docker.sock"
        -e "E2E_DEPLOYMENT_ID=${E2E_DEPLOYMENT_ID}"
    )
    if [ -n "$cpu_limit" ]; then
        runner_command+=(--cpus "$cpu_limit")
    fi
    local env_arg
    for env_arg in "${env_args[@]}"; do
        runner_command+=(-e "$env_arg")
    done
    runner_command+=("${PLAYWRIGHT_IMAGE}" "${playwright_command[@]}")
    local status=0
    python3 "${ROOT_DIR}/scripts/run_with_timeout.py" \
        --timeout-seconds "$timeout_seconds" \
        --grace-seconds "$grace_seconds" \
        -- "${runner_command[@]}" || status=$?
    if [ "$status" -ne 0 ]; then
        echo "Playwright runner diagnostics: ${runner_name}" >&2
        docker inspect --format 'state={{.State.Status}} exit={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} error={{.State.Error}}' "$runner_name" >&2 || true
        docker logs --timestamps "$runner_name" >&2 || true
    fi
    docker rm -f "$runner_name" >/dev/null 2>&1 || true
    return "$status"
}

build_image() {
    local target="$1"
    local image="$2"
    local log_file="${LOG_DIR}/image-build-${target}.log"
    mkdir -p "${LOG_DIR}"
    if DOCKER_BUILDKIT=1 docker build --progress=plain -f docker/Dockerfile --target "$target" -t "$image" . >"$log_file" 2>&1; then
        return 0
    else
        local status=$?
        echo "Failed to build E2E image target=${target}; full log: ${log_file}" >&2
        tail -n 160 "$log_file" >&2
        return "$status"
    fi
}

build_images() {
    echo "Building e2e images"
    for target in api scheduler runtime worker; do
        # BuildKit layer cache keeps rebuilds cheap when a target is unchanged.
        build_image "$target" "data-forge-${target}:e2e"
    done
    build_image engine "${ENGINE_IMAGE}"
    # This enclave is discarded after the run. Reclaim its intermediate layers
    # before pulling the large Playwright image into the same daemon.
    echo "Pruning temporary BuildKit cache before pulling the Playwright image"
    docker builder prune --all --force
}

resolve_docker_socket_gid() {
    # The private daemon resolves this socket path inside its own container.
    DOCKER_SOCKET_GID="$(docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
        --entrypoint stat "${WORKER_IMAGE}" -c %g /var/run/docker.sock)"
    export DOCKER_SOCKET_GID
}

stack_up() {
    echo "E2E stack id: ${E2E_STACK_ID}"
    # Clean only this run's namespaced project. A retained stack from any
    # other run must never satisfy this run's readiness checks.
    stack_down
    build_images
    resolve_docker_socket_gid
    echo "Starting e2e stack (postgres, rustfs, openai-fixture, api, runtime, worker, scheduler)"
    if ! "${COMPOSE[@]}" up -d --wait; then
        echo "E2E stack failed readiness; capturing service logs" >&2
        dump_service_logs startup
        return 1
    fi
    echo "E2E stack is ready"
}

stack_down() {
    # Stop services first so the coordinator cannot spawn engines during teardown,
    # then sweep the spawned engines (label filter) both before and after: an
    # engine claimed in the race window would otherwise leak past `down -v`.
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-playwright-shard" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-playwright-load-probe" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-runtime-architecture" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-shared-fixture-bootstrap" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" stop >/dev/null 2>&1 || true
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    docker network rm "${E2E_DOCKER_NETWORK}" >/dev/null 2>&1 || true
}

dump_service_logs() {
    if [ -z "$LOG_DIR" ]; then
        return
    fi
    local phase="${1:-current}"
    local print_tails="${2:-0}"
    local phase_dir="${LOG_DIR}/${phase}"
    mkdir -p "$phase_dir"
    local service
    for service in api runtime worker scheduler rustfs openai-fixture; do
        "${COMPOSE[@]}" logs --no-color "$service" >"$phase_dir/${service}.log" 2>&1 || true
    done
    # Engine container stderr/stdout: job tracebacks (datasource load errors,
    # engine-side crashes) only surface here, never in the coordinator log.
    docker ps -a --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" --format '{{.Names}}' \
        | while read -r engine_name; do
            docker logs --timestamps "$engine_name" >"${phase_dir}/engine-${engine_name}.log" 2>&1 || true
        done
    if [ "$print_tails" -eq 1 ]; then
        echo "::group::service log tails"
        for service in api runtime worker scheduler rustfs openai-fixture; do
            echo "--- ${service} ---"
            tail -n 100 "$phase_dir/${service}.log" || true
        done
        echo "::endgroup::"
    fi
}

dump_slow_requests() {
    if [ -z "$LOG_DIR" ]; then
        return
    fi
    local phase="${1:-current}"
    local phase_dir="${LOG_DIR}/${phase}"
    mkdir -p "$phase_dir"
    if [[ "${LOG_REQUESTS_ENABLED:-false}" == "true" ]]; then
        "${COMPOSE[@]}" exec -T postgres psql -U dataforge -d dataforge -c \
            "SELECT round(duration_ms::numeric) AS ms, status, method, path, to_char(ts, 'HH24:MI:SS') AS at
             FROM request_logs
             WHERE duration_ms > 5000 AND ts > now() - interval '3 hours'
            ORDER BY duration_ms DESC LIMIT 40;" \
            >"$phase_dir/slow-requests.log" 2>&1 || true
    else
        printf '%s\n' \
            'Request-log persistence is disabled for E2E load runs.' \
            'Use api.log for correlated slow-request warnings and request-traces for browser timings.' \
            >"$phase_dir/slow-requests.log"
    fi
    "${COMPOSE[@]}" exec -T postgres psql -X -U dataforge -d dataforge -c \
        "SELECT pid,
                application_name,
                state,
                COALESCE(wait_event_type, '') AS wait_type,
                COALESCE(wait_event, '') AS wait_event,
                round(extract(epoch FROM clock_timestamp() - query_start) * 1000) AS query_ms,
                round(extract(epoch FROM clock_timestamp() - xact_start) * 1000) AS transaction_ms,
                pg_blocking_pids(pid) AS blocked_by,
                md5(query) AS query_fingerprint,
                regexp_replace(left(query, 320), '[[:space:]]+', ' ', 'g') AS query_sample
         FROM pg_stat_activity
         WHERE datname = current_database()
           AND pid <> pg_backend_pid()
           AND (state = 'active' OR (state = 'idle in transaction' AND xact_start IS NOT NULL))
         ORDER BY cardinality(pg_blocking_pids(pid)) DESC, query_start NULLS LAST
         LIMIT 100;" \
        >"$phase_dir/database-activity-snapshot.log" 2>&1 || true
}

start_database_activity_sampler() {
    if [ -z "$LOG_DIR" ] || [ -n "$DB_ACTIVITY_SAMPLER_PID" ]; then
        return
    fi
    local phase="${1:-current}"
    local phase_dir="${LOG_DIR}/${phase}"
    local output="${phase_dir}/database-activity.tsv"
    mkdir -p "$phase_dir"
    : >"$output"
    (
        sampler_command_pid=""
        sampler_sleep_pid=""
        stop_sampler() {
            if [ -n "$sampler_command_pid" ]; then
                kill "$sampler_command_pid" >/dev/null 2>&1 || true
                wait "$sampler_command_pid" >/dev/null 2>&1 || true
            fi
            if [ -n "$sampler_sleep_pid" ]; then
                kill "$sampler_sleep_pid" >/dev/null 2>&1 || true
                wait "$sampler_sleep_pid" >/dev/null 2>&1 || true
            fi
            exit 0
        }
        trap stop_sampler TERM INT
        while true; do
            "${COMPOSE[@]}" exec -T postgres psql -X -U dataforge -d dataforge -AtF $'\t' -c \
                "SELECT clock_timestamp(), pid, application_name, state,
                        COALESCE(wait_event_type, ''), COALESCE(wait_event, ''),
                        round(extract(epoch FROM clock_timestamp() - query_start) * 1000),
                        round(extract(epoch FROM clock_timestamp() - xact_start) * 1000),
                        pg_blocking_pids(pid)::text, md5(query),
                        regexp_replace(left(query, 320), '[[:space:]]+', ' ', 'g')
                 FROM pg_stat_activity
                 WHERE datname = current_database()
                   AND pid <> pg_backend_pid()
                   AND (state = 'active' OR (state = 'idle in transaction' AND xact_start IS NOT NULL))
                 ORDER BY cardinality(pg_blocking_pids(pid)) DESC, query_start NULLS LAST
                 LIMIT 100;" >>"$output" 2>&1 &
            sampler_command_pid=$!
            wait "$sampler_command_pid" || true
            sampler_command_pid=""
            sleep 5 &
            sampler_sleep_pid=$!
            wait "$sampler_sleep_pid" || true
            sampler_sleep_pid=""
        done
    ) &
    DB_ACTIVITY_SAMPLER_PID=$!
}

stop_database_activity_sampler() {
    if [ -z "$DB_ACTIVITY_SAMPLER_PID" ]; then
        return
    fi
    kill "$DB_ACTIVITY_SAMPLER_PID" >/dev/null 2>&1 || true
    wait "$DB_ACTIVITY_SAMPLER_PID" >/dev/null 2>&1 || true
    DB_ACTIVITY_SAMPLER_PID=""
}

start_load_probe_resource_sampler() {
    if [ -z "$LOG_DIR" ] || [ -n "$LOAD_PROBE_RESOURCE_SAMPLER_PID" ]; then
        return
    fi
    local phase="${1:-load-probe}"
    local runner_name="${2:-dataforge-e2e-${E2E_STACK_ID}-playwright-load-probe}"
    local phase_dir="${LOG_DIR}/${phase}"
    mkdir -p "$phase_dir"
    python3 "${ROOT_DIR}/scripts/e2e/resource_sampler.py" \
        "dataforge-e2e-${E2E_STACK_ID}" \
        "$E2E_DEPLOYMENT_ID" \
        "$runner_name" \
        "$$" \
        "$phase_dir/runner-resource.tsv" \
        >"$phase_dir/resource-sampler.log" 2>&1 &
    LOAD_PROBE_RESOURCE_SAMPLER_PID=$!
}

stop_load_probe_resource_sampler() {
    if [ -z "$LOAD_PROBE_RESOURCE_SAMPLER_PID" ]; then
        return
    fi
    kill -TERM "$LOAD_PROBE_RESOURCE_SAMPLER_PID" >/dev/null 2>&1 || true
    wait "$LOAD_PROBE_RESOURCE_SAMPLER_PID" >/dev/null 2>&1 || true
    LOAD_PROBE_RESOURCE_SAMPLER_PID=""
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
    local run_stamp="${E2E_GLOBAL_RUN_STAMP}-shard-${shard_index}-of-${shard_total}"
    cd "${ROOT_DIR}/packages/frontend"
    # Playwright wipes its output directory on start. Give every shard a
    # completely independent root so no runner can remove another runner's
    # output path during parallel startup.
    local artifacts_dir="${E2E_ARTIFACTS_DIR}/playwright-shards/shard${shard_index}"
    local runner_artifacts_root
    runner_artifacts_root="$(playwright_artifacts_root)"
    local output_dir="${runner_artifacts_root}/playwright-shards/shard${shard_index}/test-results"
    local report_dir="${runner_artifacts_root}/playwright-shards/shard${shard_index}/playwright-report"
    local request_trace_root="${PLAYWRIGHT_REQUEST_TRACE_DIR:-$(playwright_artifacts_root)/request-traces}"
    local timeout_seconds="${E2E_TIMEOUT_SECONDS:-0}"
    if [ "$timeout_seconds" -eq 0 ]; then
        timeout_seconds=3600
    fi
    mkdir -p "${artifacts_dir}/test-results" "${artifacts_dir}/playwright-report"
    if [ "${NORMAL_TEST_FILES+x}" = x ] && [ "${#NORMAL_TEST_FILES[@]}" -gt 0 ]; then
        echo "Running Playwright subset: ${NORMAL_TEST_FILES[*]}"
    fi
    if [ "${NORMAL_GREP_ARGS+x}" = x ] && [ "${#NORMAL_GREP_ARGS[@]}" -gt 0 ]; then
        echo "Playwright grep arguments: ${NORMAL_GREP_ARGS[*]}"
    fi
    echo "Starting Playwright shard ${shard_index}/${shard_total} (${PW_E2E_WORKERS} browser workers)"
    local runner_env=(
        "PW_E2E_WORKERS=${PW_E2E_WORKERS}"
        "E2E_CONCURRENCY_BROWSERS=${E2E_CONCURRENCY_BROWSERS:-}"
        "PLAYWRIGHT_TEST_TIMEOUT_MS=${PLAYWRIGHT_TEST_TIMEOUT_MS:-}"
        "DEFAULT_NAMESPACE=${DEFAULT_NAMESPACE}"
        "E2E_GLOBAL_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}"
        "E2E_ARTIFACTS_DIR=$(playwright_artifacts_root)"
        "E2E_SHARED_FIXTURES_READ_ONLY=1"
        "E2E_RUN_STAMP=${run_stamp}"
        "PLAYWRIGHT_BASE_URL=${E2E_PLAYWRIGHT_BASE_URL}"
        "PLAYWRIGHT_OUTPUT_DIR=${output_dir}"
        "PLAYWRIGHT_HTML_OUTPUT_DIR=${report_dir}"
        "PLAYWRIGHT_JSON_REPORT=${PLAYWRIGHT_JSON_REPORT:-}"
        "PLAYWRIGHT_REQUEST_TRACE_DIR=${request_trace_root}/shard${shard_index}"
    )
    local test_args=("--shard=${shard_index}/${shard_total}")
    if [ "${#NORMAL_TEST_FILES[@]}" -gt 0 ]; then
        test_args+=("${NORMAL_TEST_FILES[@]}")
    fi
    if [ "${#NORMAL_GREP_ARGS[@]}" -gt 0 ]; then
        test_args+=("${NORMAL_GREP_ARGS[@]}")
    fi
    run_playwright "$timeout_seconds" "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        "dataforge-e2e-${E2E_STACK_ID}-playwright-shard${shard_index}" \
        "${runner_env[@]}" -- "${test_args[@]}"
}

run_playwright_concurrency_probe() {
    cd "${ROOT_DIR}/packages/frontend"
    local artifacts_dir="${E2E_ARTIFACTS_DIR}/playwright-load-probe"
    local runner_artifacts_root
    runner_artifacts_root="$(playwright_artifacts_root)"
    local output_dir="${runner_artifacts_root}/playwright-load-probe/test-results"
    local report_dir="${runner_artifacts_root}/playwright-load-probe/playwright-report"
    local request_trace_root="${PLAYWRIGHT_REQUEST_TRACE_DIR:-$(playwright_artifacts_root)/request-traces}"
    local timeout_seconds="${E2E_TIMEOUT_SECONDS:-1500}"
    if [ "$timeout_seconds" -eq 0 ]; then
        timeout_seconds=600
    fi
    mkdir -p "${artifacts_dir}/test-results" "${artifacts_dir}/playwright-report"
    if [[ ! "${E2E_LOAD_PROBE_CPUS:-}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "Invalid or missing derived E2E_LOAD_PROBE_CPUS: ${E2E_LOAD_PROBE_CPUS:-unset}" >&2
        return 2
    fi
    echo "Starting isolated Playwright load probe (${E2E_CONCURRENCY_BROWSERS:-50} tabs, account-isolated contexts across a bounded Chromium process pool, CPU limit ${E2E_LOAD_PROBE_CPUS} vCPU)"
    local runner_env=(
        "E2E_CONCURRENCY_BROWSERS=${E2E_CONCURRENCY_BROWSERS:-50}"
        "E2E_GLOBAL_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}"
        "E2E_ARTIFACTS_DIR=$(playwright_artifacts_root)"
        "E2E_SHARED_FIXTURES_READ_ONLY=1"
        "E2E_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}-load-probe"
        "PLAYWRIGHT_BASE_URL=${E2E_PLAYWRIGHT_BASE_URL}"
        "PLAYWRIGHT_JSON_REPORT=${output_dir}/playwright-report.json"
        "PLAYWRIGHT_TEST_TIMEOUT_MS=300000"
        "PW_E2E_WORKERS=1"
        "PLAYWRIGHT_OUTPUT_DIR=${output_dir}"
        "PLAYWRIGHT_HTML_OUTPUT_DIR=${report_dir}"
        "PLAYWRIGHT_REQUEST_TRACE_DIR=${request_trace_root}/load-probe"
    )
    run_playwright "$timeout_seconds" "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        "dataforge-e2e-${E2E_STACK_ID}-playwright-load-probe" \
        --cpu-limit "$E2E_LOAD_PROBE_CPUS" \
        "${runner_env[@]}" -- tests/concurrency.test.ts
}

run_playwright_architecture_tests() {
    cd "${ROOT_DIR}/packages/frontend"
    local artifacts_dir="${E2E_ARTIFACTS_DIR}/runtime-architecture"
    local runner_artifacts_root
    runner_artifacts_root="$(playwright_artifacts_root)"
    local output_dir="${runner_artifacts_root}/runtime-architecture/test-results"
    local report_dir="${runner_artifacts_root}/runtime-architecture/playwright-report"
    local request_trace_root="${PLAYWRIGHT_REQUEST_TRACE_DIR:-$(playwright_artifacts_root)/request-traces}"
    mkdir -p "${artifacts_dir}/test-results" "${artifacts_dir}/playwright-report"
    echo "Running serialized runtime architecture regressions"
    local runner_env=(
        "PW_E2E_WORKERS=1"
        "E2E_API_WORKERS=${E2E_API_WORKERS:-${WORKERS:-4}}"
        "DEFAULT_NAMESPACE=${DEFAULT_NAMESPACE}"
        "E2E_GLOBAL_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}"
        "E2E_ARTIFACTS_DIR=$(playwright_artifacts_root)"
        "E2E_SHARED_FIXTURES_READ_ONLY=1"
        "E2E_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}-runtime-architecture"
        "PLAYWRIGHT_BASE_URL=${E2E_PLAYWRIGHT_BASE_URL}"
        "PLAYWRIGHT_OUTPUT_DIR=${output_dir}"
        "PLAYWRIGHT_HTML_OUTPUT_DIR=${report_dir}"
        "PLAYWRIGHT_JSON_REPORT=${output_dir}/playwright-report.json"
        "PLAYWRIGHT_REQUEST_TRACE_DIR=${request_trace_root}/runtime-architecture"
        "E2E_OPENAI_FIXTURE_URL=${E2E_OPENAI_FIXTURE_URL}"
        "E2E_OPENROUTER_API_KEY=${E2E_OPENROUTER_API_KEY:-}"
    )
    if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
        runner_env+=("PLAYWRIGHT_GREP=${PLAYWRIGHT_GREP}")
    fi
    local playwright_args=("${ARCHITECTURE_TEST_FILES[@]}")
    if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
        playwright_args+=(--grep "${PLAYWRIGHT_GREP}")
    fi
    run_playwright "${E2E_ARCHITECTURE_TIMEOUT_SECONDS:-1200}" "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        "dataforge-e2e-${E2E_STACK_ID}-runtime-architecture" \
        "${runner_env[@]}" -- "${playwright_args[@]}"
}

run_connected_session_probe() {
    local sessions="$1"
    local run_index="$2"
    local runner_name="dataforge-e2e-${E2E_STACK_ID}-session-capacity-${run_index}"
    local probe_script="${ROOT_DIR}/scripts/e2e/connected_session_probe.py"
    local run_status=0
    local probe_cpu_limit=1.0
    if awk -v ratio="${E2E_SESSION_ACTIVE_RATIO:-0}" 'BEGIN { exit !(ratio > 0) }'; then
        probe_cpu_limit=2.0
    fi

    echo "Starting connected-session capacity probe ${run_index}/${E2E_SESSION_REPEATS:-3} (${sessions} unique accounts, active_ratio=${E2E_SESSION_ACTIVE_RATIO:-0}, probe_cpu=${probe_cpu_limit})"
    start_load_probe_resource_sampler "session-capacity-${run_index}" "$runner_name"
    python3 "${ROOT_DIR}/scripts/run_with_timeout.py" \
        --timeout-seconds "${E2E_SESSION_PROBE_TIMEOUT_SECONDS:-900}" \
        --grace-seconds "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        -- \
        docker run --init --shm-size=128m --pids-limit=4096 \
            --name "$runner_name" \
            --label "io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" \
            --network "$E2E_DOCKER_NETWORK" \
            --cpus="$probe_cpu_limit" --memory=768m \
            -v "${probe_script}:/connected_session_probe.py:ro" \
            --entrypoint python3 \
            data-forge-api:e2e \
            /connected_session_probe.py \
            --sessions "$sessions" \
            --api-url http://api:8000 \
            --namespace "$DEFAULT_NAMESPACE" \
            --run-id "${E2E_GLOBAL_RUN_STAMP}-session-${run_index}" \
            --duration-seconds "${E2E_SESSION_DURATION_SECONDS:-60}" \
            --active-ratio "${E2E_SESSION_ACTIVE_RATIO:-0}" \
            --heartbeat-seconds "${E2E_SESSION_HEARTBEAT_SECONDS:-10}" \
            --registration-concurrency "${E2E_SESSION_REGISTRATION_CONCURRENCY:-16}" \
            --connect-concurrency "${E2E_SESSION_CONNECT_CONCURRENCY:-64}" || run_status=$?
    stop_load_probe_resource_sampler

    if [ "$run_status" -ne 0 ]; then
        echo "Connected-session probe failed; capturing its container diagnostics" >&2
        docker inspect --format 'state={{.State.Status}} exit={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} error={{.State.Error}}' \
            "$runner_name" >&2 || true
        docker logs --timestamps "$runner_name" >&2 || true
    fi
    docker rm -f "$runner_name" >/dev/null 2>&1 || true
    return "$run_status"
}

prepare_playwright_selection() {
    NORMAL_TEST_FILES=()
    NORMAL_GREP_ARGS=()
    RUN_CONCURRENCY_PROBE=0
    RUN_ARCHITECTURE_TESTS=0

    if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
        NORMAL_GREP_ARGS+=(--grep "${PLAYWRIGHT_GREP}")
    fi

    if [ -z "${PLAYWRIGHT_TEST_FILES:-}" ]; then
        # Keep architecture and load cases out of normal shards by file path.
        RUN_CONCURRENCY_PROBE=1
        RUN_ARCHITECTURE_TESTS=1
        local listed_files
        if ! listed_files="$(select_default_playwright_tests "${ROOT_DIR}/packages/frontend")"; then
            return 1
        fi
        local test_file
        while IFS= read -r test_file; do
            NORMAL_TEST_FILES+=("$test_file")
        done <<<"$listed_files"
        return
    fi

    local requested_files=()
    read -r -a requested_files <<<"${PLAYWRIGHT_TEST_FILES}"
    local test_file
    for test_file in "${requested_files[@]}"; do
        case "$test_file" in
            tests/runtime-architecture.test.ts|./tests/runtime-architecture.test.ts|runtime-architecture.test.ts|tests/datasource-compute-isolation.test.ts|./tests/datasource-compute-isolation.test.ts|datasource-compute-isolation.test.ts)
                RUN_ARCHITECTURE_TESTS=1
                ;;
            tests/concurrency.test.ts|./tests/concurrency.test.ts|concurrency.test.ts)
                RUN_CONCURRENCY_PROBE=1
                ;;
            *)
                NORMAL_TEST_FILES+=("$test_file")
                ;;
        esac
    done
}

bootstrap_shared_fixtures() (
    cd "${ROOT_DIR}/packages/frontend"
    local artifacts_dir="${E2E_ARTIFACTS_DIR}/shared-fixture-bootstrap"
    local runner_artifacts_root
    runner_artifacts_root="$(playwright_artifacts_root)"
    local output_dir="${runner_artifacts_root}/shared-fixture-bootstrap/test-results"
    local report_dir="${runner_artifacts_root}/shared-fixture-bootstrap/playwright-report"
    local timeout_seconds="${E2E_FIXTURE_BOOTSTRAP_TIMEOUT_SECONDS:-600}"
    local bootstrap_test_timeout_ms=$((timeout_seconds * 1000))
    local bootstrap_namespace_fixtures="${E2E_BOOTSTRAP_NAMESPACE_FIXTURES:-1}"
    if [ -n "${PLAYWRIGHT_TEST_FILES:-}" ] && [ "${#NORMAL_TEST_FILES[@]}" -eq 0 ]; then
        bootstrap_namespace_fixtures=0
    fi
    mkdir -p "${artifacts_dir}/test-results" "${artifacts_dir}/playwright-report"
    echo "Bootstrapping immutable shared E2E datasets once before browser shards"
    run_playwright "$timeout_seconds" "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        "dataforge-e2e-${E2E_STACK_ID}-shared-fixture-bootstrap" \
        "E2E_GLOBAL_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}" \
        "E2E_ARTIFACTS_DIR=$(playwright_artifacts_root)" \
        "E2E_RUN_STAMP=${E2E_GLOBAL_RUN_STAMP}-bootstrap" \
        "E2E_BOOTSTRAP_SHARED_FIXTURES=1" \
        "E2E_BOOTSTRAP_NAMESPACE_FIXTURES=${bootstrap_namespace_fixtures}" \
        "PW_E2E_WORKERS=1" \
        "PLAYWRIGHT_TEST_TIMEOUT_MS=${bootstrap_test_timeout_ms}" \
        "PLAYWRIGHT_BASE_URL=${E2E_PLAYWRIGHT_BASE_URL}" \
        "PLAYWRIGHT_OUTPUT_DIR=${output_dir}" \
        "PLAYWRIGHT_HTML_OUTPUT_DIR=${report_dir}" --
)

action="${1:-all}"
case "$action" in
    capacity)
        sessions="${E2E_SESSION_CONNECTIONS:-2000}"
        repeats="${E2E_SESSION_REPEATS:-3}"
        active_ratio="${E2E_SESSION_ACTIVE_RATIO:-0}"
        if [[ ! "$sessions" =~ ^[1-9][0-9]*$ ]] || [ "${#sessions}" -gt 6 ]; then
            echo "E2E_SESSION_CONNECTIONS must be a positive integer no greater than 999999; got '${sessions}'." >&2
            exit 2
        fi
        if [[ ! "$repeats" =~ ^[1-9][0-9]*$ ]] || [ "${#repeats}" -gt 3 ]; then
            echo "E2E_SESSION_REPEATS must be a positive integer no greater than 999; got '${repeats}'." >&2
            exit 2
        fi
        if [[ ! "$active_ratio" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] || \
            ! awk -v value="$active_ratio" 'BEGIN { exit !(value >= 0 && value <= 1) }'; then
            echo "E2E_SESSION_ACTIVE_RATIO must be between 0 and 1 inclusive; got '${active_ratio}'." >&2
            exit 2
        fi
        active_http_sessions=$(awk -v sessions="$sessions" -v ratio="$active_ratio" 'BEGIN { print int(sessions * ratio + 0.999999) }')
        minimum_connections=$((sessions + (2 * active_http_sessions) + 64))
        if [ "$WORKER_CONNECTIONS" -lt "$minimum_connections" ]; then
            WORKER_CONNECTIONS="$minimum_connections"
        fi
        export WORKER_CONNECTIONS
        echo "Connected-session profile: sessions=${sessions} active_ratio=${active_ratio} WORKER_CONNECTIONS=${WORKER_CONNECTIONS} (at least ${sessions} WebSocket + $((2 * active_http_sessions)) active HTTP + 64) API_WORKERS=${WORKERS}"
        cleanup_capacity() {
            status=$?
            stop_load_probe_resource_sampler
            stop_database_activity_sampler
            stack_down
            exit "$status"
        }
        trap cleanup_capacity EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        mkdir -p "${E2E_ARTIFACTS_DIR}/session-capacity"
        stack_up
        start_database_activity_sampler session-capacity
        probe_status=0
        for run_index in $(seq 1 "$repeats"); do
            run_connected_session_probe "$sessions" "$run_index" || probe_status=$?
            dump_service_logs "session-capacity-${run_index}" "$probe_status"
            dump_slow_requests "session-capacity-${run_index}"
            if [ "$probe_status" -ne 0 ]; then
                break
            fi
        done
        stop_database_activity_sampler
        exit "$probe_status"
        ;;
    all)
        cleanup() {
            status=$?
            stop_load_probe_resource_sampler
            stop_database_activity_sampler
            stack_down
            exit "$status"
        }
        trap cleanup EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM
        if [ -n "$LOG_DIR" ]; then
            mkdir -p "$LOG_DIR"
        fi
        stack_up

        shards="${E2E_SHARDS:-3}"
        # Runner output lives under this run's unique artifact root. Never
        # delete shared test artifacts as part of an E2E invocation.
        mkdir -p "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}"
        mkdir -p "${E2E_ARTIFACTS_DIR}/playwright-load-probe/test-results" \
            "${E2E_ARTIFACTS_DIR}/playwright-load-probe/playwright-report"
        for shard in $(seq 1 "$shards"); do
            mkdir -p "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}/shard${shard}/test-results" "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}/shard${shard}/playwright-report"
        done
        prepare_playwright_selection
        bootstrap_status=0
        bootstrap_shared_fixtures || bootstrap_status=$?
        dump_service_logs shared-fixture-bootstrap "$bootstrap_status"
        dump_slow_requests shared-fixture-bootstrap
        if [ "$bootstrap_status" -ne 0 ]; then
            exit "$bootstrap_status"
        fi
        only_concurrency_probe=0
        if [ "${#NORMAL_TEST_FILES[@]}" -eq 0 ] && [ -n "${PLAYWRIGHT_TEST_FILES:-}" ] \
            && [ "$RUN_CONCURRENCY_PROBE" -eq 1 ] && [ "$RUN_ARCHITECTURE_TESTS" -eq 0 ]; then
            only_concurrency_probe=1
        fi
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
            echo "The 50-tab concurrency test is isolated into its own runner"
        fi
        if [ "${#NORMAL_TEST_FILES[@]}" -eq 0 ] && [ -n "${PLAYWRIGHT_TEST_FILES:-}" ]; then
            if [ "$RUN_ARCHITECTURE_TESTS" -eq 1 ] && [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
                echo "No ordinary Playwright files selected; running the architecture suite and isolated concurrency probe"
            elif [ "$RUN_ARCHITECTURE_TESTS" -eq 1 ]; then
                echo "No ordinary Playwright files selected; running only the architecture suite"
            else
                echo "No ordinary Playwright files selected; running only the isolated concurrency probe"
            fi
        else
            echo "Running ${shards} Playwright shard runner(s), ${PW_E2E_WORKERS} browser workers each"
        fi
        pids=()
        failed=0
        set +e
        if [ "${#NORMAL_TEST_FILES[@]}" -gt 0 ] || [ -z "${PLAYWRIGHT_TEST_FILES:-}" ]; then
            start_database_activity_sampler full-suite
            for shard in $(seq 1 "$shards"); do
                run_playwright_shard "$shard" "$shards" &
                pids+=($!)
            done
        fi
        if [ "${#pids[@]}" -gt 0 ]; then
            for pid in "${pids[@]}"; do
                wait "$pid" || failed=1
            done
            dump_service_logs full-suite "$failed"
        fi
        stop_database_activity_sampler
        if [ "$RUN_ARCHITECTURE_TESTS" -eq 1 ]; then
            start_database_activity_sampler runtime-architecture
            run_playwright_architecture_tests || failed=1
            stop_database_activity_sampler
            dump_service_logs runtime-architecture
            dump_slow_requests runtime-architecture
        fi
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
            if [ "$only_concurrency_probe" -ne 1 ]; then
                wait_for_runtime_drain || failed=1
                dump_slow_requests full-suite
                # Stop the worker first so it drains under the active lease,
                # then restart the coordinator and start a fresh worker manager.
                echo "Restarting the E2E coordinator and worker for a clean load-probe pool"
                if "${COMPOSE[@]}" stop --timeout 60 worker && "${COMPOSE[@]}" stop --timeout 60 runtime; then
                    "${COMPOSE[@]}" up -d --wait runtime worker || failed=1
                else
                    failed=1
                fi
            fi
            start_load_probe_resource_sampler
            start_database_activity_sampler load-probe
            run_playwright_concurrency_probe || failed=1
            stop_load_probe_resource_sampler
            stop_database_activity_sampler
        fi
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
            # Keep successful load-probe evidence too: latency can be poor
            # without producing a failed browser assertion.
            dump_service_logs load-probe "$failed"
        fi
        set -e
        wait_for_runtime_drain
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
            dump_slow_requests load-probe
        else
            dump_slow_requests full-suite
        fi
        exit "$failed"
        ;;
    *)
        echo "usage: test_e2e.sh" >&2
        exit 1
        ;;
esac

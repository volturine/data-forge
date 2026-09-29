#!/usr/bin/env bash
# E2E harness for the containerized application stack.
#
# Exactly one app stack (postgres, rustfs, api, runtime, worker, scheduler) exists per
# run. CI runs Playwright containers on the Compose network; local runs use the
# host browser through its Tailscale address so Chromium does not compete with
# the stack for Docker Desktop VM CPU. The 50-tab probe has its own runner and
# spreads pages across Chromium processes to avoid a single-client bottleneck.
#
# Usage:
#   test_e2e.sh              # stack up, parallel Playwright shards, stack down
#   test_e2e.sh stack-down   # stop and remove a leftover stack
set -euo pipefail
set -a; source docker/env/e2e.env; set +a
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

ROOT_DIR="$(pwd)"
if [[ -n "${E2E_ARTIFACTS_DIR:-}" && "${E2E_ARTIFACTS_DIR}" != /* ]]; then
    E2E_ARTIFACTS_DIR="${ROOT_DIR}/${E2E_ARTIFACTS_DIR}"
fi
if [[ -n "${E2E_STACK_ID:-}" ]]; then
    E2E_STACK_ID_EXPLICIT=1
else
    E2E_STACK_ID="run-$(date +%Y%m%d%H%M%S)-$$"
    E2E_STACK_ID_EXPLICIT=0
fi
if [[ ! "${E2E_STACK_ID}" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ ]]; then
    echo "E2E_STACK_ID must be 1-32 lowercase letters, digits, underscores, or hyphens, starting with a letter or digit" >&2
    exit 2
fi
E2E_ARTIFACTS_DIR="${E2E_ARTIFACTS_DIR:-${ROOT_DIR}/.e2e-artifacts/${E2E_STACK_ID}}"
E2E_ARTIFACTS_CONTAINER_DIR="${E2E_ARTIFACTS_CONTAINER_DIR:-/work/.e2e-artifacts/${E2E_STACK_ID}}"
if [[ "${E2E_ARTIFACTS_CONTAINER_DIR}" != /* ]]; then
    E2E_ARTIFACTS_CONTAINER_DIR="/work/${E2E_ARTIFACTS_CONTAINER_DIR#./}"
fi
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
CONCURRENCY_TEST_TITLE_PATTERN='runs [0-9]+ parallel tabs across [0-9]+ accounts'

NORMAL_TEST_FILES=()
NORMAL_GREP_ARGS=()
RUN_CONCURRENCY_PROBE=0
DB_ACTIVITY_SAMPLER_PID=""

PLAYWRIGHT_VERSION="$(node -p "require('./packages/frontend/node_modules/playwright/package.json').version")"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble"

playwright_artifacts_root() {
    if [ -n "${CI:-}" ]; then
        printf '%s' "${E2E_ARTIFACTS_CONTAINER_DIR}"
    else
        printf '%s' "${E2E_ARTIFACTS_DIR}"
    fi
}

run_playwright() {
    local timeout_seconds="$1"
    local grace_seconds="$2"
    local runner_name="$3"
    shift 3
    local env_args=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
        env_args+=("$1")
        shift
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
    local runner_command=()
    if [ -n "${CI:-}" ]; then
        runner_command=(
            docker run --rm --init --shm-size=1gb
            --name "$runner_name"
            --network "$E2E_DOCKER_NETWORK"
            -v "${ROOT_DIR}:/work"
            -w /work/packages/frontend
            -e "CI=${CI}"
        )
        local env_arg
        for env_arg in "${env_args[@]}"; do
            runner_command+=(-e "$env_arg")
        done
        runner_command+=("${PLAYWRIGHT_IMAGE}" "${playwright_command[@]}")
    else
        if [ ! -x ./node_modules/.bin/playwright ]; then
            echo "Local Playwright is not installed; run 'just install' first" >&2
            return 2
        fi
        runner_command=(env "${env_args[@]}" "${playwright_command[@]}")
    fi
    python3 "${ROOT_DIR}/scripts/run_with_timeout.py" \
        --timeout-seconds "$timeout_seconds" \
        --grace-seconds "$grace_seconds" \
        -- "${runner_command[@]}"
}

build_images() {
    echo "Building e2e images"
    for target in api scheduler runtime worker; do
        # BuildKit layer cache keeps rebuilds cheap when a target is unchanged.
        DOCKER_BUILDKIT=1 docker build -q -f docker/Dockerfile --target "$target" -t "data-forge-${target}:e2e" . >/dev/null
    done
    DOCKER_BUILDKIT=1 docker build -q -f docker/Dockerfile --target engine -t "${ENGINE_IMAGE}" . >/dev/null
}

resolve_docker_socket_gid() {
    # The gid the runtime coordinator needs is the one *containers* see: on Docker Desktop
    # the daemon runs in a VM where the socket is root-owned, which does not
    # match the host inode. Ask the worker image instead of stat-ing the host.
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
    echo "Starting e2e stack (postgres, rustfs, api, runtime, worker, scheduler)"
    if ! "${COMPOSE[@]}" up -d --wait; then
        echo "E2E stack failed readiness; capturing service logs" >&2
        dump_service_logs startup
        return 1
    fi
    resolve_playwright_base_url
    echo "E2E stack is ready"
}

resolve_playwright_base_url() {
    if [ -n "${CI:-}" ]; then
        # CI runners address their isolated Compose network directly; no
        # service is running on this Mac in that environment.
        E2E_PLAYWRIGHT_BASE_URL="http://api:8000"
    else
        local tailscale_ip host_port published_port
        tailscale_ip="$(dig +short A rolands-mac-mini.bee-justice.ts.net | awk 'NF {print; exit}')"
        if [ -z "${tailscale_ip}" ]; then
            echo "Could not resolve this Mac's Tailscale IPv4 address" >&2
            return 1
        fi
        published_port="$("${COMPOSE[@]}" port api 8000)"
        host_port="${published_port##*:}"
        if [[ ! "${host_port}" =~ ^[0-9]+$ ]]; then
            echo "Could not resolve the published E2E API port from: ${published_port}" >&2
            return 1
        fi
        E2E_PLAYWRIGHT_BASE_URL="http://${tailscale_ip}:${host_port}"
    fi
    export E2E_PLAYWRIGHT_BASE_URL
    echo "Playwright API address: ${E2E_PLAYWRIGHT_BASE_URL}"
}

stack_down() {
    # Stop services first so the coordinator cannot spawn engines during teardown,
    # then sweep the spawned engines (label filter) both before and after: an
    # engine claimed in the race window would otherwise leak past `down -v`.
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-playwright-shard" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-playwright-load-probe" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker ps -aq --filter "name=dataforge-e2e-${E2E_STACK_ID}-shared-fixture-bootstrap" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" stop >/dev/null 2>&1 || true
    docker ps -aq --filter "label=io.dataforge.deployment=${E2E_DEPLOYMENT_ID}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    docker network rm "${E2E_DOCKER_NETWORK}" >/dev/null 2>&1 || true
}

normalize_e2e_artifact_ownership() {
    if [ -z "${CI:-}" ] || [ ! -d "${E2E_ARTIFACTS_DIR}" ]; then
        return
    fi

    docker run --rm --network none \
        -v "${ROOT_DIR}:/work" \
        -e "ARTIFACT_UID=$(id -u)" \
        -e "ARTIFACT_GID=$(id -g)" \
        -e "E2E_ARTIFACTS_DIR=${E2E_ARTIFACTS_CONTAINER_DIR}" \
        -e "PLAYWRIGHT_ARTIFACTS_DIR=/work/packages/frontend/tests/.artifacts" \
        --entrypoint sh "${PLAYWRIGHT_IMAGE}" \
        -c 'for path in "$E2E_ARTIFACTS_DIR" "$PLAYWRIGHT_ARTIFACTS_DIR"; do if [ -d "$path" ]; then chown -R "$ARTIFACT_UID:$ARTIFACT_GID" "$path"; fi; done'
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
    for service in api runtime worker scheduler rustfs; do
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
        for service in api runtime worker scheduler rustfs; do
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
    echo "Starting isolated Playwright load probe (${E2E_CONCURRENCY_BROWSERS:-50} tabs, up to 10 tabs per Chromium process)"
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
        "${runner_env[@]}" -- tests/concurrency.test.ts
}

prepare_playwright_selection() {
    NORMAL_TEST_FILES=()
    NORMAL_GREP_ARGS=()
    RUN_CONCURRENCY_PROBE=0

    if [ -n "${PLAYWRIGHT_GREP:-}" ]; then
        NORMAL_GREP_ARGS+=(--grep "${PLAYWRIGHT_GREP}")
    fi

    if [ -z "${PLAYWRIGHT_TEST_FILES:-}" ]; then
        # The full suite always includes the 50-tab probe, but the ordinary
        # shards must not put its 50 live pages into one of their renderers.
        RUN_CONCURRENCY_PROBE=1
        NORMAL_GREP_ARGS+=(--grep-invert "${CONCURRENCY_TEST_TITLE_PATTERN}")
        return
    fi

    local requested_files=()
    read -r -a requested_files <<<"${PLAYWRIGHT_TEST_FILES}"
    local test_file
    for test_file in "${requested_files[@]}"; do
        case "$test_file" in
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
    all)
        keep_stack="${E2E_KEEP_STACK:-0}"
        cleanup() {
            status=$?
            stop_database_activity_sampler
            if ! normalize_e2e_artifact_ownership; then
                echo "Failed to restore ownership of E2E artifacts for the next checkout" >&2
                if [ "$status" -eq 0 ]; then
                    status=1
                fi
            fi
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

        shards="${E2E_SHARDS:-3}"
        # Runner output lives under this run's unique artifact root. Never
        # delete shared/local test artifacts as part of a CI/E2E invocation.
        mkdir -p "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}"
        mkdir -p "${E2E_ARTIFACTS_DIR}/playwright-load-probe/test-results" \
            "${E2E_ARTIFACTS_DIR}/playwright-load-probe/playwright-report"
        for shard in $(seq 1 "$shards"); do
            mkdir -p "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}/shard${shard}/test-results" "${PLAYWRIGHT_SHARD_ARTIFACTS_DIR}/shard${shard}/playwright-report"
        done
        prepare_playwright_selection
        bootstrap_shared_fixtures
        only_concurrency_probe=0
        if [ "${#NORMAL_TEST_FILES[@]}" -eq 0 ] && [ -n "${PLAYWRIGHT_TEST_FILES:-}" ]; then
            only_concurrency_probe=1
        fi
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
            echo "The 50-tab concurrency test is isolated into its own runner"
        fi
        if [ "${#NORMAL_TEST_FILES[@]}" -eq 0 ] && [ -n "${PLAYWRIGHT_TEST_FILES:-}" ]; then
            echo "No ordinary Playwright files selected; running only the isolated concurrency probe"
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
        fi
        stop_database_activity_sampler
        if [ "$failed" -ne 0 ]; then
            dump_service_logs full-suite
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
            start_database_activity_sampler load-probe
            run_playwright_concurrency_probe || failed=1
            stop_database_activity_sampler
        fi
        if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ] || [ "$failed" -ne 0 ]; then
            # Keep successful load-probe evidence too: latency can be poor
            # without producing a failed browser assertion.
            log_phase=full-suite
            if [ "$RUN_CONCURRENCY_PROBE" -eq 1 ]; then
                log_phase=load-probe
            fi
            dump_service_logs "$log_phase" "$failed"
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
    stack-down)
        if [ "$E2E_STACK_ID_EXPLICIT" -ne 1 ]; then
            echo "Set E2E_STACK_ID to the exact run id printed by test_e2e.sh before stopping a retained stack." >&2
            exit 2
        fi
        stack_down
        ;;
    *)
        echo "usage: test_e2e.sh [all|stack-down]" >&2
        exit 1
        ;;
esac

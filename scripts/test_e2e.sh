#!/usr/bin/env bash
set -euo pipefail
set -a; source config/env/e2e.env; set +a
# Playwright forces FORCE_COLOR=1 for worker processes, so drop NO_COLOR to
# keep the warning scanner clean and avoid conflicting color policies.
unset NO_COLOR
unset VIRTUAL_ENV
export UV_PYTHON="${E2E_PYTHON_VERSION}"
ROOT_DIR="$(pwd)"
DATA_DIR="${DATA_DIR}-run-$$"
export DATA_DIR
export ENGINE_IMAGE="data-forge-polars-engine:latest"
ENGINE_DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
export ENGINE_DOCKER_HOST
export ENGINE_DOCKER_NETWORK="dataforge-e2e-engine-$$"
export ENGINE_CONNECT_HOST="127.0.0.1"
export ENGINE_ALLOW_GLOBAL_OBJECT_STORE_CREDENTIALS="true"
# Parallel Playwright workers start engines concurrently. Cap each engine to
# one Polars thread so compute does not monopolize the host.
export POLARS_CORES_AVAILABLE="${E2E_POLARS_CORES_AVAILABLE:-1}"
# Keep engines warm across steps of the same identity; thrashing Docker create
# is the main e2e wall-time cost after the Docker cutover.
export ENGINE_IDLE_TTL_SECONDS="${E2E_ENGINE_IDLE_TTL_SECONDS:-120}"
export ENGINE_IDLE_REAP_INTERVAL_SECONDS="${E2E_ENGINE_IDLE_REAP_INTERVAL_SECONDS:-15}"
LOG_DIR="${E2E_LOG_DIR:-}"
PLAYWRIGHT_ARTIFACTS_DIR="${ROOT_DIR}/packages/frontend/tests/.artifacts/playwright"
PLAYWRIGHT_CONTAINER="dataforge-e2e-playwright-$$"
PLAYWRIGHT_LABEL="data-forge.test-playwright=1"
PLAYWRIGHT_PORT=""
PG_CONTAINER="dataforge-e2e-pg-$$"
PG_LABEL="data-forge.test-postgres=1"
PG_VOLUME="${PG_CONTAINER}-data"
PG_PORT=""
RUSTFS_CONTAINER="dataforge-e2e-rustfs-$$"
RUSTFS_LABEL="data-forge.test-rustfs=1"
RUSTFS_PORT=""
ENGINE_NETWORK_LABEL="data-forge.test-engine-network=1"
pick_host_port() {
    python - "$@" <<'PY'
import socket
import sys

reserved = {int(value) for value in sys.argv[1:] if value}
for _ in range(100):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port not in reserved:
        print(port)
        raise SystemExit(0)
raise SystemExit("failed to choose an unreserved free TCP port")
PY
}
INTERNAL_GRPC_PORT="$(pick_host_port "${PORT}" "${FRONTEND_PORT}")"
WORKER_DATA_PLANE_GRPC_PORT="$(pick_host_port "${PORT}" "${FRONTEND_PORT}" "${INTERNAL_GRPC_PORT}")"
export INTERNAL_GRPC_PORT
export INTERNAL_GRPC_TARGET="127.0.0.1:${INTERNAL_GRPC_PORT}"
export WORKER_DATA_PLANE_GRPC_PORT
export WORKER_DATA_PLANE_GRPC_TARGET="127.0.0.1:${WORKER_DATA_PLANE_GRPC_PORT}"
echo "Using e2e internal gRPC port ${INTERNAL_GRPC_PORT}"
echo "Using e2e worker data-plane gRPC port ${WORKER_DATA_PLANE_GRPC_PORT}"
kill_tree() {
    local pid="$1"
    if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
        return
    fi
    local child
    while read -r child; do
        kill_tree "$child"
    done < <(pgrep -P "$pid" || true)
    kill "$pid" >/dev/null 2>&1 || true
}
kill_tree_force() {
    local pid="$1"
    if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
        return
    fi
    local child
    while read -r child; do
        kill_tree_force "$child"
    done < <(pgrep -P "$pid" || true)
    kill -9 "$pid" >/dev/null 2>&1 || true
}
wait_for_processes_to_exit() {
    local deadline="$1"
    shift
    while [ "$SECONDS" -lt "$deadline" ]; do
        local any_alive=0
        for pid in "$@"; do
            if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
                any_alive=1
                break
            fi
        done
        if [ "$any_alive" -eq 0 ]; then
            break
        fi
        sleep 0.5
    done
}
terminate_processes() {
    for pid in "$@"; do
        kill_tree "$pid"
    done
    wait_for_processes_to_exit "$((SECONDS + 10))" "$@"
    for pid in "$@"; do
        kill_tree_force "$pid"
    done
}
dump_service_logs() {
    if [ -z "$LOG_DIR" ] || [ ! -d "$LOG_DIR" ]; then
        return
    fi
    local service
    for service in backend worker scheduler frontend; do
        local log_file="$LOG_DIR/${service}.log"
        if [ ! -f "$log_file" ]; then
            continue
        fi
        echo "::group::${service} service log tail"
        tail -n 200 "$log_file" || true
        echo "::endgroup::"
    done
}
cleanup() {
    status=$?
    docker rm -f "${PLAYWRIGHT_CONTAINER}" >/dev/null 2>&1 || true
    terminate_processes "${FRONTEND_PID:-}" "${SCHEDULER_PID:-}" "${WORKER_PID:-}"
    terminate_processes "${BACKEND_PID:-}"
    # Worker death can leave labelled engines on the private network; remove them
    # before network teardown so the next suite does not hit name/network conflicts.
    if [ -n "${ENGINE_DOCKER_NETWORK:-}" ]; then
        docker network inspect -f '{{range .Containers}}{{.Name}} {{end}}' "${ENGINE_DOCKER_NETWORK}" 2>/dev/null \
            | tr ' ' '\n' \
            | while read -r container_name; do
                [ -z "$container_name" ] && continue
                [ "$container_name" = "${RUSTFS_CONTAINER}" ] && continue
                docker rm -f "$container_name" >/dev/null 2>&1 || true
            done
    fi
    docker rm -f "${RUSTFS_CONTAINER}" >/dev/null 2>&1 || true
    docker network rm "${ENGINE_DOCKER_NETWORK}" >/dev/null 2>&1 || true
    docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
    docker volume rm -f "${PG_VOLUME}" >/dev/null 2>&1 || true
    lsof -ti "tcp:${PORT}" | xargs -r kill >/dev/null 2>&1 || true
    lsof -ti "tcp:${FRONTEND_PORT}" | xargs -r kill >/dev/null 2>&1 || true
    lsof -ti "tcp:${INTERNAL_GRPC_PORT}" | xargs -r kill >/dev/null 2>&1 || true
    lsof -ti "tcp:${WORKER_DATA_PLANE_GRPC_PORT}" | xargs -r kill >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
lsof -ti "tcp:${PORT}" | xargs -r kill >/dev/null 2>&1 || true
lsof -ti "tcp:${FRONTEND_PORT}" | xargs -r kill >/dev/null 2>&1 || true
lsof -ti "tcp:${INTERNAL_GRPC_PORT}" | xargs -r kill >/dev/null 2>&1 || true
lsof -ti "tcp:${WORKER_DATA_PLANE_GRPC_PORT}" | xargs -r kill >/dev/null 2>&1 || true
if [ -n "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi
echo "Starting e2e Postgres"
docker ps -aq --filter "label=${PG_LABEL}" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker volume ls -q --filter "label=${PG_LABEL}" | xargs -r docker volume rm -f >/dev/null 2>&1 || true
docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
docker volume rm -f "${PG_VOLUME}" >/dev/null 2>&1 || true
docker volume create --label "${PG_LABEL}" "${PG_VOLUME}" >/dev/null
PG_PORT="$(pick_host_port "${PORT}" "${FRONTEND_PORT}" "${INTERNAL_GRPC_PORT}" "${WORKER_DATA_PLANE_GRPC_PORT}")"
docker run -d --rm \
    --label "${PG_LABEL}" \
    --name "${PG_CONTAINER}" \
    -v "${PG_VOLUME}:/var/lib/postgresql" \
    -e POSTGRES_DB=dataforge \
    -e POSTGRES_USER=dataforge \
    -e POSTGRES_PASSWORD=dataforge \
    -p "127.0.0.1:${PG_PORT}:5432" \
    postgres:18-alpine -c max_connections=300 >/dev/null
if [ -z "$PG_PORT" ]; then
    echo "Failed to resolve e2e Postgres host port" >&2
    exit 1
fi
export DATABASE_URL="postgresql+psycopg://dataforge:dataforge@127.0.0.1:${PG_PORT}/dataforge"
deadline=$((SECONDS + 90))
until docker exec "${PG_CONTAINER}" pg_isready -U dataforge -d dataforge >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "Timed out waiting for e2e Postgres" >&2
        exit 1
    fi
    sleep 1
done

echo "Starting e2e RustFS"
docker ps -aq --filter "label=${RUSTFS_LABEL}" | xargs -r docker rm -f >/dev/null 2>&1 || true
docker rm -f "${RUSTFS_CONTAINER}" >/dev/null 2>&1 || true
docker network create --label "${ENGINE_NETWORK_LABEL}" "${ENGINE_DOCKER_NETWORK}" >/dev/null
RUSTFS_PORT="$(pick_host_port "${PORT}" "${FRONTEND_PORT}" "${INTERNAL_GRPC_PORT}" "${WORKER_DATA_PLANE_GRPC_PORT}" "${PG_PORT}")"
docker run -d --rm \
    --label "${RUSTFS_LABEL}" \
    --name "${RUSTFS_CONTAINER}" \
    --network "${ENGINE_DOCKER_NETWORK}" \
    -e RUSTFS_ACCESS_KEY="${OBJECT_STORE_ACCESS_KEY}" \
    -e RUSTFS_SECRET_KEY="${OBJECT_STORE_SECRET_KEY}" \
    -p "127.0.0.1:${RUSTFS_PORT}:9000" \
    rustfs/rustfs:1.0.0-rc.1 /data >/dev/null
if [ -z "$RUSTFS_PORT" ]; then
    echo "Failed to resolve e2e RustFS host port" >&2
    exit 1
fi
export OBJECT_STORE_ENDPOINT="http://127.0.0.1:${RUSTFS_PORT}"
export ENGINE_OBJECT_STORE_ENDPOINT="http://${RUSTFS_CONTAINER}:9000"
deadline=$((SECONDS + 60))
until [ "$(curl -s -o /dev/null -w '%{http_code}' "${OBJECT_STORE_ENDPOINT}" || true)" != "000" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "Timed out waiting for e2e RustFS" >&2
        exit 1
    fi
    sleep 1
done

echo "Starting e2e services"
echo "Building e2e Polars engine image"
# BuildKit layer cache keeps rebuilds cheap when the engine target is unchanged.
DOCKER_BUILDKIT=1 docker build -q -f docker/Dockerfile --target engine -t "${ENGINE_IMAGE}" . >/dev/null
if [ -n "$LOG_DIR" ]; then
    (cd packages/backend && exec uv run --no-env-file main.py) >"$LOG_DIR/backend.log" 2>&1 & BACKEND_PID=$!
fi
if [ -z "$LOG_DIR" ]; then
    (cd packages/backend && exec uv run --no-env-file main.py) & BACKEND_PID=$!
fi
wait_for_url() {
    local url="$1"
    local label="$2"
    local deadline=$((SECONDS + 90))
    until curl -fs "$url" >/dev/null 2>&1; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "Timed out waiting for ${label} at ${url}" >&2
            dump_service_logs >&2
            exit 1
        fi
        sleep 1
    done
}
wait_for_runtime_worker() {
    local kind="$1"
    local min_count="$2"
    local label="$3"
    local deadline=$((SECONDS + 120))
    local sql="SELECT count(*) FROM public.runtime_workers WHERE kind = '${kind}' AND stopped_at IS NULL;"
    while true; do
        local count
        count="$(docker exec "${PG_CONTAINER}" psql -U dataforge -d dataforge -Atc "$sql" 2>/dev/null || echo 0)"
        count="${count//$'\n'/}"
        if [ "${count:-0}" -ge "$min_count" ]; then
            return
        fi
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "Timed out waiting for ${label} registration" >&2
            exit 1
        fi
        sleep 1
    done
}
echo "Waiting for backend readiness"
wait_for_url "http://127.0.0.1:${PORT}/health/ready" "backend readiness"
echo "Backend is ready"
echo "Starting e2e worker, scheduler, and frontend"
if [ -n "$LOG_DIR" ]; then
    (cd packages/worker && exec uv run --no-env-file main.py) >"$LOG_DIR/worker.log" 2>&1 & WORKER_PID=$!
    (cd packages/scheduler && exec uv run --no-env-file main.py) >"$LOG_DIR/scheduler.log" 2>&1 & SCHEDULER_PID=$!
    (cd packages/frontend && bun run panda:codegen && bun run build && exec node ./node_modules/vite/bin/vite.js preview) >"$LOG_DIR/frontend.log" 2>&1 & FRONTEND_PID=$!
fi
if [ -z "$LOG_DIR" ]; then
    (cd packages/worker && exec uv run --no-env-file main.py) & WORKER_PID=$!
    (cd packages/scheduler && exec uv run --no-env-file main.py) & SCHEDULER_PID=$!
    (cd packages/frontend && bun run panda:codegen && bun run build && exec node ./node_modules/vite/bin/vite.js preview) & FRONTEND_PID=$!
fi
echo "Waiting for runtime worker registrations"
wait_for_runtime_worker "build_manager" 1 "worker build manager"
wait_for_runtime_worker "scheduler" 1 "scheduler"
echo "Runtime workers are ready"
echo "Waiting for frontend readiness"
wait_for_url "http://127.0.0.1:${FRONTEND_PORT}" "frontend"
echo "Frontend is ready"
PLAYWRIGHT_WORKERS="${PW_E2E_WORKERS:-}"
if [ -z "${PLAYWRIGHT_WORKERS}" ]; then
    echo "PW_E2E_WORKERS must be set before running e2e tests" >&2
    exit 1
fi
if [ -n "${CI:-}" ]; then
    # Engine containers attach and detach throughout the suite. Chromium treats
    # those host veth changes as network changes, which can abort unrelated page
    # requests. Keep the browser in its own stable network namespace and use
    # Playwright's native loopback exposure to reach the host-run test services.
    PLAYWRIGHT_VERSION="$(node -p "require('./packages/frontend/node_modules/playwright/package.json').version")"
    PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble"
    PLAYWRIGHT_PORT="$(pick_host_port "${PORT}" "${FRONTEND_PORT}" "${INTERNAL_GRPC_PORT}" "${WORKER_DATA_PLANE_GRPC_PORT}" "${PG_PORT}" "${RUSTFS_PORT}")"
    docker ps -aq --filter "label=${PLAYWRIGHT_LABEL}" | xargs -r docker rm -f >/dev/null 2>&1 || true
    docker run -d --rm --init \
        --label "${PLAYWRIGHT_LABEL}" \
        --name "${PLAYWRIGHT_CONTAINER}" \
        -v "${ROOT_DIR}:/work:ro" \
        -w /work/packages/frontend \
        -p "127.0.0.1:${PLAYWRIGHT_PORT}:3000" \
        "${PLAYWRIGHT_IMAGE}" \
        node node_modules/playwright/cli.js run-server --host 0.0.0.0 --port 3000 >/dev/null
    deadline=$((SECONDS + 30))
    until docker logs "${PLAYWRIGHT_CONTAINER}" 2>&1 | grep -q "Listening on ws://"; do
        if [ "$SECONDS" -ge "$deadline" ] || [ "$(docker inspect -f '{{.State.Running}}' "${PLAYWRIGHT_CONTAINER}" 2>/dev/null || true)" != "true" ]; then
            echo "Failed to start isolated Playwright browser server" >&2
            docker logs "${PLAYWRIGHT_CONTAINER}" >&2 || true
            exit 1
        fi
        sleep 0.25
    done
    export PW_TEST_CONNECT_WS_ENDPOINT="ws://127.0.0.1:${PLAYWRIGHT_PORT}/"
    export PW_TEST_CONNECT_EXPOSE_NETWORK="<loopback>"
    echo "Playwright browser is isolated from Docker engine network churn"
fi
echo "Starting Playwright e2e tests"
echo "Using ${PLAYWRIGHT_WORKERS} worker(s)"
rm -rf "${PLAYWRIGHT_ARTIFACTS_DIR}"
mkdir -p "${PLAYWRIGHT_ARTIFACTS_DIR}"
mkdir -p "${PLAYWRIGHT_ARTIFACTS_DIR}/test-results"
mkdir -p "${PLAYWRIGHT_ARTIFACTS_DIR}/playwright-report"

run_playwright() {
    cd "${ROOT_DIR}/packages/frontend"
    local output_dir="$PWD/tests/.artifacts/playwright/test-results"
    local report_dir="$PWD/tests/.artifacts/playwright/playwright-report"
    local timeout_seconds="${E2E_TIMEOUT_SECONDS:-0}"
    # A local canonical run must stay bounded. The Docker-engine cutover pushed
    # the full suite past ten minutes on common hardware, so the ceiling is now
    # fifteen minutes; CI keeps its explicit, larger cold-run budget.
    if [ -z "${CI:-}" ] && { [ "$timeout_seconds" -eq 0 ] || [ "$timeout_seconds" -gt 900 ]; }; then
        timeout_seconds=900
    fi
    mkdir -p "$output_dir" "$report_dir"
    # Optional profiling subset, e.g. PLAYWRIGHT_TEST_FILES="tests/profile.test.ts tests/monitoring.test.ts".
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
    PLAYWRIGHT_DISABLE_WEB_SERVER=true \
    PLAYWRIGHT_HTML_OUTPUT_DIR="$report_dir" \
    PLAYWRIGHT_OUTPUT_DIR="$output_dir" \
    python3 ../../scripts/run_with_timeout.py \
        --timeout-seconds "$timeout_seconds" \
        --grace-seconds "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        -- ./node_modules/.bin/playwright test --config=playwright.config.ts \
        ${test_files[@]+"${test_files[@]}"} \
        ${grep_args[@]+"${grep_args[@]}"}
}

run_playwright

echo "Waiting for e2e runtime work to drain"
# Let ordinary asynchronous work finish, but do not let a request orphaned by
# a destructive navigation test dominate the local suite runtime.
deadline=$((SECONDS + 15))
while true; do
    active_runtime_work="$(docker exec "${PG_CONTAINER}" psql -U dataforge -d dataforge -Atc \
        "SELECT
            (SELECT count(*) FROM public.compute_requests WHERE status IN (1, 2)) +
            (SELECT count(*) FROM public.build_jobs WHERE status IN ('queued', 'leased', 'running'));" \
        2>/dev/null || echo 1)"
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

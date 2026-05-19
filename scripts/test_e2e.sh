#!/usr/bin/env bash
set -euo pipefail
set -a; source packages/shared/e2e.env; set +a
unset VIRTUAL_ENV
export UV_PYTHON="${E2E_PYTHON_VERSION}"
DATA_DIR="${DATA_DIR}-run-$$"
export DATA_DIR
LOG_DIR="${E2E_LOG_DIR:-}"
PG_CONTAINER="dataforge-e2e-pg-$$"
PG_PORT=""
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
cleanup() {
    status=$?
    for pid in ${FRONTEND_PID:-} ${SCHEDULER_PID:-} ${WORKER_PID:-} ${BACKEND_PID:-}; do
        kill_tree "$pid"
    done
    local deadline=$((SECONDS + 10))
    while [ "$SECONDS" -lt "$deadline" ]; do
        local any_alive=0
        for pid in ${FRONTEND_PID:-} ${SCHEDULER_PID:-} ${WORKER_PID:-} ${BACKEND_PID:-}; do
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
    for pid in ${FRONTEND_PID:-} ${SCHEDULER_PID:-} ${WORKER_PID:-} ${BACKEND_PID:-}; do
        kill_tree_force "$pid"
    done
    docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
    lsof -ti "tcp:${PORT}" | xargs -r kill >/dev/null 2>&1 || true
    lsof -ti "tcp:${FRONTEND_PORT}" | xargs -r kill >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
lsof -ti "tcp:${PORT}" | xargs -r kill >/dev/null 2>&1 || true
lsof -ti "tcp:${FRONTEND_PORT}" | xargs -r kill >/dev/null 2>&1 || true
if [ -n "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi
echo "Starting e2e Postgres"
docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
docker run -d --rm \
    --name "${PG_CONTAINER}" \
    -e POSTGRES_DB=dataforge \
    -e POSTGRES_USER=dataforge \
    -e POSTGRES_PASSWORD=dataforge \
    -p 127.0.0.1::5432 \
    postgres:18-alpine -c max_connections=300 >/dev/null
PG_PORT="$(docker port "${PG_CONTAINER}" 5432/tcp | awk -F: '{print $NF}')"
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
echo "Starting e2e services"
if [ -n "$LOG_DIR" ]; then
    (cd packages/backend && exec uv run --no-env-file main.py) >"$LOG_DIR/backend.log" 2>&1 & BACKEND_PID=$!
    (cd packages/worker-manager && exec uv run --no-env-file main.py) >"$LOG_DIR/worker.log" 2>&1 & WORKER_PID=$!
    (cd packages/scheduler && exec uv run --no-env-file main.py) >"$LOG_DIR/scheduler.log" 2>&1 & SCHEDULER_PID=$!
    (cd packages/frontend && bun run predev && exec node ./node_modules/vite/bin/vite.js dev) >"$LOG_DIR/frontend.log" 2>&1 & FRONTEND_PID=$!
fi
if [ -z "$LOG_DIR" ]; then
    (cd packages/backend && exec uv run --no-env-file main.py) & BACKEND_PID=$!
    (cd packages/worker-manager && exec uv run --no-env-file main.py) & WORKER_PID=$!
    (cd packages/scheduler && exec uv run --no-env-file main.py) & SCHEDULER_PID=$!
    (cd packages/frontend && bun run predev && exec node ./node_modules/vite/bin/vite.js dev) & FRONTEND_PID=$!
fi
wait_for_url() {
    local url="$1"
    local label="$2"
    local deadline=$((SECONDS + 90))
    until curl -fsS "$url" >/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "Timed out waiting for ${label} at ${url}" >&2
            exit 1
        fi
        sleep 1
    done
}
echo "Waiting for backend readiness"
wait_for_url "http://127.0.0.1:${PORT}/health/ready" "backend readiness"
echo "Backend is ready"
echo "Waiting for frontend readiness"
wait_for_url "http://127.0.0.1:${FRONTEND_PORT}" "frontend"
echo "Frontend is ready"
echo "Starting Playwright e2e tests across 4 shards"
mkdir -p packages/frontend/tests/.artifacts/playwright
for shard_index in 1 2 3 4; do
    mkdir -p "packages/frontend/tests/.artifacts/playwright/shard-${shard_index}-of-4/test-results"
done

run_playwright_shard() {
    local shard_label="$1"
    shift
    local shard_index="${shard_label%%/*}"
    local shard_total="${shard_label##*/}"
    echo "Starting Playwright shard ${shard_label}"
    cd packages/frontend
    local output_dir="$PWD/tests/.artifacts/playwright/shard-${shard_index}-of-${shard_total}/test-results"
    rm -rf "$output_dir"
    mkdir -p "$output_dir"
    PLAYWRIGHT_DISABLE_WEB_SERVER=true \
    PLAYWRIGHT_OUTPUT_DIR="$output_dir" \
    exec python3 ../../scripts/run_with_timeout.py \
        --timeout-seconds "${E2E_TIMEOUT_SECONDS:-0}" \
        --grace-seconds "${E2E_TIMEOUT_GRACE_SECONDS:-30}" \
        --heartbeat-seconds "${E2E_HEARTBEAT_SECONDS:-0}" \
        -- npx playwright test --config=playwright.config.ts "$@"
}

set +e
pids=()
(
    run_playwright_shard "1/4" \
        tests/analysis-editor.test.ts \
        tests/analysis-crud.test.ts \
        tests/analysis-locking.test.ts \
        tests/lineage.test.ts
) & pids+=("$!")
(
    run_playwright_shard "2/4" \
        --grep "Monitoring –|Navigation –|Profile –|Analyses – SQL/Polars snippet export|Datasources – detail view|Datasources – preview pagination|Datasources – column stats panel|Datasources – config tab interactions" \
        tests/monitoring.test.ts \
        tests/navigation.test.ts \
        tests/profile.test.ts \
        tests/sql-polars-snippet-export.test.ts \
        tests/datasources.test.ts
) & pids+=("$!")
(
    run_playwright_shard "3/4" \
        --grep "Analyses –|Datasources – list & management|Datasources – upload page|Namespace –|Build Preview –|Cancel Build –" \
        tests/analysis-operations.test.ts \
        tests/datasources.test.ts \
        tests/namespace-isolation.test.ts \
        tests/build-preview.test.ts \
        tests/cancel-build.test.ts
) & pids+=("$!")
(
    run_playwright_shard "4/4" \
        tests/analysis-pipeline.test.ts \
        tests/analysis-output.test.ts \
        tests/udfs.test.ts
) & pids+=("$!")
status=0
for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
        status=1
    fi
done
set -e
exit "$status"


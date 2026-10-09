# Data Forge task runner

default: dev

pytest := 'env -u VIRTUAL_ENV uv run python -m pytest -c pyproject.toml -q'
python := 'env -u VIRTUAL_ENV uv run python'
buf := './node_modules/.bin/buf'

install:
    just generate-protocol
    cd packages/backend && uv sync
    cd packages/scheduler && uv sync
    cd packages/worker && uv sync
    cd packages/frontend && bun install

# Update dependencies to the newest available releases.
# - frontend: bun update --latest updates package.json ranges to latest majors
# - python: uv lock --upgrade refreshes to the latest versions allowed by pyproject constraints
update-deps:
    @echo "Updating backend dependencies to latest allowed releases..."
    cd packages/backend && uv lock --upgrade --resolution highest && uv sync
    @echo "Updating frontend dependencies to latest releases (including majors)..."
    cd packages/frontend && bun update --latest
    @echo "Updating scheduler dependencies to latest allowed releases..."
    cd packages/scheduler && uv lock --upgrade --resolution highest && uv sync
    @echo "Updating worker dependencies to latest allowed releases..."
    cd packages/worker && uv lock --upgrade --resolution highest && uv sync

dev:
    #!/usr/bin/env bash
    set -euo pipefail
    just generate-protocol
    set -a; source docker/env/dev.env; set +a
    just compute-worker-image "$DF_COMPUTE_WORKER_IMAGE"
    # The coordinator and worker manager run as separate package processes;
    # only the worker service owns Docker access and compute-worker lifecycle.
    export COMPUTE_WORKER_DOCKER_HOST="$DF_COMPUTE_WORKER_DOCKER_HOST"
    export COMPUTE_WORKER_IMAGE="$DF_COMPUTE_WORKER_IMAGE"
    export COMPUTE_WORKER_DOCKER_NETWORK="$DF_COMPUTE_WORKER_DOCKER_NETWORK"
    export COMPUTE_WORKER_RPC_PORT="$DF_COMPUTE_WORKER_RPC_PORT"
    export COMPUTE_WORKER_START_TIMEOUT_SECONDS="$DF_COMPUTE_WORKER_START_TIMEOUT_SECONDS"
    export COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS="$DF_COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS"
    export COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS="$DF_COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS"
    export COMPUTE_WORKER_CONNECT_HOST=127.0.0.1
    docker network inspect "$COMPUTE_WORKER_DOCKER_NETWORK" >/dev/null 2>&1 || docker network create "$COMPUTE_WORKER_DOCKER_NETWORK" >/dev/null
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_postgres.py
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_rustfs.py
    (cd packages/backend && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/backend && env -u VIRTUAL_ENV DATABASE_POOL_SIZE="$COMPUTE_WORKERS" DATABASE_MAX_OVERFLOW=13 uv run --env-file ../../docker/env/dev.env runtime_coordinator.py) & \
    (cd packages/worker && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/scheduler && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/frontend && bun run dev) & wait

# Ensure the compute-worker image exists locally; build it if missing.
compute-worker-image tag:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! docker image inspect "{{tag}}" >/dev/null 2>&1; then
        echo "Compute-worker image {{tag}} not found; building..."
        docker build -f docker/Dockerfile --target compute-worker -t "{{tag}}" .
    fi

# Build the frontend and run the fixed production roles from source.
prod:
    #!/usr/bin/env bash
    set -euo pipefail
    just generate-protocol
    cd packages/frontend
    bun run build
    cd ../..
    set -a
    source docker/env/prod.env
    set +a
    export COMPUTE_WORKER_DOCKER_HOST="$DF_COMPUTE_WORKER_DOCKER_HOST"
    export COMPUTE_WORKER_DOCKER_NETWORK="$DF_COMPUTE_WORKER_DOCKER_NETWORK"
    export COMPUTE_WORKER_IMAGE="$DF_COMPUTE_WORKER_IMAGE"
    export COMPUTE_WORKER_RPC_PORT="$DF_COMPUTE_WORKER_RPC_PORT"
    export COMPUTE_WORKER_START_TIMEOUT_SECONDS="$DF_COMPUTE_WORKER_START_TIMEOUT_SECONDS"
    export COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS="$DF_COMPUTE_WORKER_SHUTDOWN_GRACE_SECONDS"
    export COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS="$DF_COMPUTE_WORKER_HEARTBEAT_INTERVAL_SECONDS"
    export COMPUTE_WORKER_CONNECT_HOST=127.0.0.1
    pids=()
    shutdown() {
        trap - EXIT INT TERM
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                kill -TERM "$pid" 2>/dev/null || true
            fi
        done
        for pid in "${pids[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
    }
    trap 'status=$?; shutdown; exit "$status"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    (cd packages/backend && env -u VIRTUAL_ENV uv run main.py) &
    pids+=("$!")
    (cd packages/backend && env -u VIRTUAL_ENV DATABASE_POOL_SIZE="$COMPUTE_WORKERS" DATABASE_MAX_OVERFLOW=13 uv run runtime_coordinator.py) &
    pids+=("$!")
    (cd packages/worker && env -u VIRTUAL_ENV uv run main.py) &
    pids+=("$!")
    (cd packages/scheduler && env -u VIRTUAL_ENV uv run main.py) &
    pids+=("$!")
    while true; do
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                continue
            fi
            set +e
            wait "$pid"
            status=$?
            set -e
            if [ "$status" -eq 0 ]; then
                echo 'A production role exited unexpectedly.' >&2
                exit 1
            fi
            exit "$status"
        done
        sleep 1
    done

dev-clean:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a; source docker/env/dev.env; set +a
    cd packages/backend
    env -u VIRTUAL_ENV uv run python - <<'PY'
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from backend_core.config import settings

    engine = create_engine(settings.database_url, isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as connection:
            schemas = list(connection.execute(text("""
                SELECT nspname
                FROM pg_namespace
                WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                  AND nspname NOT LIKE 'pg_%'
            """)).scalars())
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.execute(text('CREATE SCHEMA public'))
    except OperationalError as exc:
        if 'does not exist' not in str(exc).lower():
            raise
        print('Development database does not exist; skipping database schema reset.')
    finally:
        engine.dispose()
    PY
    cd ../..
    rm -rf .runtime/data packages/backend/data packages/scheduler/data packages/worker/data
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_rustfs.py --remove
    echo "✓ Local dev database and runtime data reset. Run 'just dev' to recreate everything."

format:
    cd packages/backend && env -u VIRTUAL_ENV uv run ruff check --select I --fix .
    cd packages/scheduler && env -u VIRTUAL_ENV uv run ruff check --select I --fix .
    cd packages/worker && env -u VIRTUAL_ENV uv run ruff check --select I --fix .
    cd packages/backend && env -u VIRTUAL_ENV uv run ruff format .
    cd packages/scheduler && env -u VIRTUAL_ENV uv run ruff format .
    cd packages/worker && env -u VIRTUAL_ENV uv run ruff format .
    cd packages/frontend && bun run format

check:
    just generate-protocol
    cd packages/backend && env -u VIRTUAL_ENV uv run ruff format --check .
    cd packages/scheduler && env -u VIRTUAL_ENV uv run ruff format --check .
    cd packages/worker && env -u VIRTUAL_ENV uv run ruff format --check .
    cd packages/backend && env -u VIRTUAL_ENV uv run ruff check .
    cd packages/scheduler && env -u VIRTUAL_ENV uv run ruff check .
    cd packages/worker && env -u VIRTUAL_ENV uv run ruff check .
    cd packages/backend && env -u VIRTUAL_ENV uv run python -m mypy .
    cd packages/scheduler && env -u VIRTUAL_ENV uv run python -m mypy .
    cd packages/worker && env -u VIRTUAL_ENV uv run python -m mypy .
    cd packages/protocol && {{buf}} format --diff --exit-code
    cd packages/protocol && {{buf}} lint
    if git cat-file -e HEAD:packages/protocol/buf.yaml 2>/dev/null; then cd packages/protocol && {{buf}} breaking --against '../../.git#branch=HEAD,subdir=packages/protocol'; else echo 'Skipping Buf breaking check: no protocol Buf module exists in HEAD yet.'; fi
    if rg -n 'remote: buf\.build/(protocolbuffers|grpc)' packages/protocol Justfile; then echo 'Protocol generation must use the local packages/protocol toolchain, not Buf remote plugins.'; exit 1; fi
    just check-protocol-generated
    scripts/check_no_generated_protocol.sh
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_package_boundaries.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_env_contracts.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_dependency_hygiene.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_code_hygiene.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_test_layout.py
    cd packages/frontend && bun run panda:codegen && bun run check && bun run lint

generate-protocol:
    #!/usr/bin/env bash
    set -euo pipefail
    cd packages/protocol
    bun install --frozen-lockfile
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    exported="$tmp/exported"
    {{buf}} export --output "$exported"
    protos=()
    while IFS= read -r proto; do
        protos+=("$proto")
    done < <(find "$exported" -name '*.proto' | sort)
    generate_into() {
        local out="$1"
        rm -rf "$out/buf" "$out/dataforge_protocol"
        mkdir -p "$out"
        env -u VIRTUAL_ENV uv run --locked python -m grpc_tools.protoc \
            -I "$exported" \
            --python_out="$out" \
            --pyi_out="$out" \
            --grpc_python_out="$out" \
            "${protos[@]}"
    }
    generate_into ../backend
    generate_into ../worker
    generate_into ../scheduler
    rm -rf ../frontend/src/lib/protocol
    PATH="$PWD/node_modules/.bin:$PATH" {{buf}} generate --template buf.gen.yaml

check-protocol-generated:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    cd packages/protocol
    bun install --frozen-lockfile
    exported="$tmp/exported"
    {{buf}} export --output "$exported"
    protos=()
    while IFS= read -r proto; do
        protos+=("$proto")
    done < <(find "$exported" -name '*.proto' | sort)
    generate_into() {
        local out="$1"
        mkdir -p "$out"
        env -u VIRTUAL_ENV uv run --locked python -m grpc_tools.protoc \
            -I "$exported" \
            --python_out="$out" \
            --pyi_out="$out" \
            --grpc_python_out="$out" \
            "${protos[@]}"
    }
    generate_into "$tmp/backend"
    generate_into "$tmp/worker"
    generate_into "$tmp/scheduler"
    ts_template="$tmp/buf.gen.yaml"
    cat > "$ts_template" <<YAML
    version: v2
    plugins:
      - local: protoc-gen-es
        out: $tmp/frontend_protocol
        opt: target=ts,json_types=true
        include_imports: true
    YAML
    PATH="$PWD/node_modules/.bin:$PATH" {{buf}} generate --template "$ts_template"
    diff -ru --exclude='__pycache__' "$tmp/backend/buf" ../backend/buf
    diff -ru --exclude='__pycache__' "$tmp/backend/dataforge_protocol" ../backend/dataforge_protocol
    diff -ru --exclude='__pycache__' "$tmp/worker/buf" ../worker/buf
    diff -ru --exclude='__pycache__' "$tmp/worker/dataforge_protocol" ../worker/dataforge_protocol
    diff -ru --exclude='__pycache__' "$tmp/scheduler/buf" ../scheduler/buf
    diff -ru --exclude='__pycache__' "$tmp/scheduler/dataforge_protocol" ../scheduler/dataforge_protocol
    diff -ru "$tmp/frontend_protocol" ../frontend/src/lib/protocol

verify:
    #!/usr/bin/env bash
    set -euo pipefail
    before="$(git status --porcelain=v1 --untracked-files=all)"
    # svelte-check's clean summary reads "0 ERRORS 0 WARNINGS 0 FILES_WITH_PROBLEMS";
    # the scanner matches the bare word, and a real failure exits nonzero anyway.
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/scan_warnings.py \
        --ignore-pattern '0 ERRORS 0 WARNINGS 0 FILES_WITH_PROBLEMS' -- just check
    after="$(git status --porcelain=v1 --untracked-files=all)"
    if [ "$before" != "$after" ]; then
        echo 'Verification mutated the worktree:' >&2
        diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
        exit 1
    fi


test:
    just test-backend-unit
    just test-backend-integration
    just test-worker
    just test-scheduler
    just test-frontend

_test-container-guard:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_TEST_CONTAINER:-}" != "1" ] || [ ! -f /.dockerenv ]; then
        echo "Raw test recipes may only run inside the containerized test runner." >&2
        exit 2
    fi

[private]
_prepare-test-services: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    cd packages/backend
    env -u VIRTUAL_ENV uv run python - <<'PY'
    import subprocess

    from tests.harness.postgres_harness import PostgresContainer, RustfsContainer

    for image in (PostgresContainer().image, RustfsContainer().image):
        print(f'Preparing test service image: {image}', flush=True)
        subprocess.run(['docker', 'pull', image], check=True)
    PY

test-backend-unit:
    TEST_TARGET=test-backend-unit scripts/test_container.sh

[private]
test-backend-unit-raw: _prepare-test-services
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/backend
    {{pytest}} -n auto --maxprocesses=8 --dist=loadfile tests --ignore=tests/integration

test-backend-integration:
    TEST_TARGET=test-backend-integration scripts/test_container.sh

[private]
test-backend-integration-raw: _prepare-test-services
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    docker build -f docker/Dockerfile --target compute-worker -t data-forge-compute-worker:integration .
    cd packages/backend
    # This test holds a compute request row lock, so run it outside the xdist load
    # to keep unrelated integration work from expiring its lease before publication.
    {{pytest}} -n auto --maxprocesses=4 --dist=loadfile tests/integration -k 'not test_postgres_runtime_coordinator_takeover_during_compute_terminal_publication'
    {{pytest}} tests/integration/test_postgres_runtime_integration.py::test_postgres_runtime_coordinator_takeover_during_compute_terminal_publication

test-worker:
    TEST_TARGET=test-worker scripts/test_container.sh

[private]
test-worker-raw: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/worker
    {{pytest}} -n auto --maxprocesses=4 --dist=loadfile tests --ignore=tests/integration

test-scheduler:
    TEST_TARGET=test-scheduler scripts/test_container.sh

[private]
test-scheduler-raw: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/scheduler
    {{pytest}} tests

[private]
test-frontend-raw: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    cd packages/frontend && bun run test:unit

test-frontend:
    TEST_TARGET=test-frontend scripts/test_container.sh

test-runtime-stability repeats='3':
    TEST_TARGET=test-runtime-stability REPEATS={{quote(repeats)}} scripts/test_container.sh

[private]
test-runtime-stability-raw repeats='3': _prepare-test-services
    #!/usr/bin/env bash
    set -euo pipefail
    for run in $(seq 1 {{repeats}}); do
        echo "Runtime stability pass ${run}/{{repeats}}"
        cd packages/backend
        {{pytest}} \
            tests/test_build_jobs_service.py \
            tests/test_compute_requests_service.py \
            tests/test_scheduler_service.py::TestScheduleClaiming::test_concurrent_schedulers_claim_due_schedule_once \
            tests/test_transitions.py \
            tests/integration/test_postgres_runtime_integration.py::test_postgres_outbox_claim_recovers_after_dispatcher_process_crash \
            tests/integration/test_postgres_runtime_integration.py::test_postgres_runtime_roles_restart_after_forced_process_exit
        cd ../..
    done

test-e2e:
    TEST_TARGET=test-e2e scripts/test_container.sh

test-e2e-capacity sessions='2000' repeats='3' duration='60' active_ratio='0' api_workers='1':
    #!/usr/bin/env bash
    set -euo pipefail
    sessions={{ quote(sessions) }}
    sessions="${sessions#sessions=}"
    if [[ ! "$sessions" =~ ^[1-9][0-9]*$ ]]; then
        echo "Expected a positive session count, got: $sessions" >&2
        exit 2
    fi
    duration={{ quote(duration) }}
    duration="${duration#duration=}"
    if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]]; then
        echo "Expected a positive steady-state duration in seconds, got: $duration" >&2
        exit 2
    fi
    repeats={{ quote(repeats) }}
    repeats="${repeats#repeats=}"
    if [[ ! "$repeats" =~ ^[1-9][0-9]*$ ]]; then
        echo "Expected a positive repeat count, got: $repeats" >&2
        exit 2
    fi
    active_ratio={{ quote(active_ratio) }}
    active_ratio="${active_ratio#active_ratio=}"
    if [[ ! "$active_ratio" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] || \
        ! awk -v value="$active_ratio" 'BEGIN { exit !(value >= 0 && value <= 1) }'; then
        echo "Expected active_ratio between 0 and 1 inclusive, got: $active_ratio" >&2
        exit 2
    fi
    api_workers={{ quote(api_workers) }}
    api_workers="${api_workers#api_workers=}"
    if [[ ! "$api_workers" =~ ^[1-9][0-9]*$ ]]; then
        echo "Expected a positive API process count, got: $api_workers" >&2
        exit 2
    fi
    WORKERS="$api_workers" E2E_API_WORKERS="$api_workers" E2E_SHARDS=1 PW_E2E_WORKERS=1 \
        E2E_SESSION_CONNECTIONS="$sessions" E2E_SESSION_REPEATS="$repeats" E2E_SESSION_DURATION_SECONDS="$duration" \
        E2E_SESSION_ACTIVE_RATIO="$active_ratio" \
        TEST_TARGET=test-e2e-capacity scripts/test_container.sh

[private]
test-e2e-raw: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    scripts/test_e2e.sh

[private]
test-e2e-capacity-raw: _test-container-guard
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    scripts/test_e2e.sh capacity

test-e2e-concurrency browsers='50':
    #!/usr/bin/env bash
    set -euo pipefail
    browsers={{quote(browsers)}}
    browsers="${browsers#browsers=}"
    if [[ ! "$browsers" =~ ^[1-9][0-9]*$ ]]; then
        echo "Expected a positive browser count, got: $browsers" >&2
        exit 2
    fi
    DATAFORGE_SKIP_PROTOCOL_GENERATE=1 E2E_SHARDS=1 PW_E2E_WORKERS=1 \
        E2E_CONCURRENCY_BROWSERS="$browsers" PLAYWRIGHT_TEST_FILES=tests/concurrency.test.ts \
        TEST_TARGET=test-e2e scripts/test_container.sh

# Containerized dev stack (source mounts + Vite). Uses the same host ports as
# `just dev` (API 8000, frontend 3000), so run either one, not both.
docker-dev:
    just generate-protocol
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/compose.yaml -f docker/compose.dev.yaml up --build

docker-dev-down:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/compose.yaml -f docker/compose.dev.yaml down -v --remove-orphans

docker-dev-logs:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/compose.yaml -f docker/compose.dev.yaml logs -f

# Build local fixed-role images and smoke-test the production compose topology.
# Overrides only DF_*_IMAGE tags and the host port; still uses
# docker/compose.yaml + docker/env/prod.env.
# Host port defaults to 8300 so the smoke stack never collides with the dev
# stacks (8000/3000) or the central deployment stacks (3300/3400).
docker-prod:
    #!/usr/bin/env bash
    set -euo pipefail
    just generate-protocol
    TAG="${DF_LOCAL_TAG:-local}"
    docker build -f docker/Dockerfile --target api -t "data-forge-api:${TAG}" .
    docker build -f docker/Dockerfile --target scheduler -t "data-forge-scheduler:${TAG}" .
    docker build -f docker/Dockerfile --target runtime -t "data-forge-runtime:${TAG}" .
    docker build -f docker/Dockerfile --target worker -t "data-forge-worker:${TAG}" .
    docker build -f docker/Dockerfile --target compute-worker -t "data-forge-compute-worker:${TAG}" .
    DF_API_IMAGE="data-forge-api:${TAG}" \
    DF_SCHEDULER_IMAGE="data-forge-scheduler:${TAG}" \
    DF_RUNTIME_IMAGE="data-forge-runtime:${TAG}" \
    DF_WORKER_IMAGE="data-forge-worker:${TAG}" \
    DF_COMPUTE_WORKER_IMAGE="data-forge-compute-worker:${TAG}" \
    DF_API_PORT="${DF_SMOKE_API_PORT:-8300}" \
      docker compose --env-file docker/env/prod.env \
        -p dataforge-prod \
        -f docker/compose.yaml \
        up -d "$@"

docker-prod-down:
    docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml down -v --remove-orphans

docker-prod-logs:
    docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/compose.yaml logs -f

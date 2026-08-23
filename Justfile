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
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_postgres.py
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_rustfs.py
    (cd packages/backend && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/scheduler && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/worker && env -u VIRTUAL_ENV uv run --env-file ../../docker/env/dev.env main.py) & \
    (cd packages/frontend && bun run dev) & wait

# Build the frontend and run the three fixed production roles from source.
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
    (cd packages/scheduler && env -u VIRTUAL_ENV uv run main.py) &
    pids+=("$!")
    (cd packages/worker && env -u VIRTUAL_ENV uv run main.py) &
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
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/scan_warnings.py -- just check
    after="$(git status --porcelain=v1 --untracked-files=all)"
    if [ "$before" != "$after" ]; then
        echo 'Verification mutated the worktree:' >&2
        diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
        exit 1
    fi


test:
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py -- just test-backend-raw
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py -- just test-frontend-raw

test-backend-raw:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/backend
    {{pytest}} tests --ignore=tests/integration
    cd ../..
    docker build -f docker/Dockerfile --target engine -t data-forge-polars-engine:integration .
    cd packages/backend
    {{pytest}} tests/integration
    cd ../worker
    {{pytest}} tests --ignore=tests/integration
    cd ../scheduler
    {{pytest}} tests

test-frontend-raw:
    cd packages/frontend && bun run test:unit

test-runtime-stability repeats='3':
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
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py --cwd . --ignore-pattern "InvalidCredentialsError: Invalid email or password" --ignore-pattern "TokenInvalidError: Token is invalid" -- scripts/test_e2e.sh

docker-dev:
    just generate-protocol
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build

docker-dev-down:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml down -v --remove-orphans

docker-dev-logs:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml logs -f

# Build local fixed-role images and smoke-test the production compose topology.
# Overrides only DF_*_IMAGE tags; still uses docker/docker-compose.yml + docker/env/prod.env.
docker-prod:
    #!/usr/bin/env bash
    set -euo pipefail
    just generate-protocol
    TAG="${DF_LOCAL_TAG:-local}"
    docker build -f docker/Dockerfile --target api -t "data-forge-api:${TAG}" .
    docker build -f docker/Dockerfile --target scheduler -t "data-forge-scheduler:${TAG}" .
    docker build -f docker/Dockerfile --target worker -t "data-forge-worker:${TAG}" .
    docker build -f docker/Dockerfile --target engine -t "data-forge-polars-engine:${TAG}" .
    DF_API_IMAGE="data-forge-api:${TAG}" \
    DF_SCHEDULER_IMAGE="data-forge-scheduler:${TAG}" \
    DF_WORKER_IMAGE="data-forge-worker:${TAG}" \
    DF_ENGINE_IMAGE="data-forge-polars-engine:${TAG}" \
      docker compose --env-file docker/env/prod.env \
        -p dataforge-prod \
        -f docker/docker-compose.yml \
        up -d "$@"

docker-prod-down:
    docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml down -v --remove-orphans

docker-prod-logs:
    docker compose --env-file docker/env/prod.env -p dataforge-prod -f docker/docker-compose.yml logs -f

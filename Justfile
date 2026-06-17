# Data Forge task runner

default: dev

pytest := 'env -u VIRTUAL_ENV uv run python -m pytest -c pyproject.toml -q'
python := 'env -u VIRTUAL_ENV uv run python'
buf := 'bunx @bufbuild/buf@1.70.0'

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
    set -a; source config/env/dev.env; set +a
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_postgres.py
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/ensure_dev_rustfs.py
    (cd packages/backend && env -u VIRTUAL_ENV uv run --env-file ../../config/env/dev.env main.py) & \
    (cd packages/scheduler && env -u VIRTUAL_ENV uv run --env-file ../../config/env/dev.env main.py) & \
    (cd packages/worker && env -u VIRTUAL_ENV uv run --env-file ../../config/env/dev.env main.py) & \
    (cd packages/frontend && bun run dev) & wait

dev-clean:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a; source config/env/dev.env; set +a
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
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/generate_ts_build_stream_types.py --check
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/generate_ts_step_types.py --check
    cd packages/protocol && {{buf}} format --diff --exit-code
    cd packages/protocol && {{buf}} lint
    if git cat-file -e HEAD:packages/protocol/buf.yaml 2>/dev/null; then cd packages/protocol && {{buf}} breaking --against '../../.git#branch=HEAD,subdir=packages/protocol'; else echo 'Skipping Buf breaking check: no protocol Buf module exists in HEAD yet.'; fi
    just check-protocol-generated
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_package_boundaries.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_env_contracts.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_dependency_hygiene.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_code_hygiene.py
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/check_test_layout.py
    cd packages/frontend && bun run panda:codegen && bun run check && bun run lint

generate-protocol:
    cd packages/protocol && {{buf}} generate

check-protocol-generated:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    mkdir -p "$tmp/backend" "$tmp/worker" "$tmp/scheduler"
    cat > "$tmp/buf.gen.yaml" <<EOF
    version: v2
    plugins:
      - remote: buf.build/protocolbuffers/python
        out: $tmp/backend
        include_imports: true
      - remote: buf.build/protocolbuffers/pyi
        out: $tmp/backend
        include_imports: true
      - remote: buf.build/grpc/python
        out: $tmp/backend
      - remote: buf.build/protocolbuffers/python
        out: $tmp/worker
        include_imports: true
      - remote: buf.build/protocolbuffers/pyi
        out: $tmp/worker
        include_imports: true
      - remote: buf.build/grpc/python
        out: $tmp/worker
      - remote: buf.build/protocolbuffers/python
        out: $tmp/scheduler
        include_imports: true
      - remote: buf.build/protocolbuffers/pyi
        out: $tmp/scheduler
        include_imports: true
      - remote: buf.build/grpc/python
        out: $tmp/scheduler
    inputs:
      - directory: proto
    EOF
    cd packages/protocol
    {{buf}} generate --template "$tmp/buf.gen.yaml"
    diff -ru --exclude='__pycache__' "$tmp/backend/buf" ../backend/buf
    diff -ru --exclude='__pycache__' "$tmp/backend/dataforge_protocol" ../backend/dataforge_protocol
    diff -ru --exclude='__pycache__' "$tmp/worker/buf" ../worker/buf
    diff -ru --exclude='__pycache__' "$tmp/worker/dataforge_protocol" ../worker/dataforge_protocol
    diff -ru --exclude='__pycache__' "$tmp/scheduler/buf" ../scheduler/buf
    diff -ru --exclude='__pycache__' "$tmp/scheduler/dataforge_protocol" ../scheduler/dataforge_protocol

verify:
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/scan_warnings.py -- just format
    env -u VIRTUAL_ENV uv run --project packages/backend python scripts/scan_warnings.py -- just check


test:
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py -- just test-backend-raw
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py -- just test-frontend-raw

test-backend-raw:
    #!/usr/bin/env bash
    set -euo pipefail
    just generate-protocol
    cd packages/backend
    {{pytest}} tests --ignore=tests/integration
    {{pytest}} tests/integration
    cd ../worker
    {{pytest}} tests --ignore=tests/integration
    cd ../scheduler
    {{pytest}} tests

test-frontend-raw:
    cd packages/frontend && bun run test:unit

test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "${DATAFORGE_SKIP_PROTOCOL_GENERATE:-}" != "1" ]; then
        just generate-protocol
    fi
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/scan_warnings.py --cwd . -- scripts/test_e2e.sh

generate-step-types:
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/generate_ts_step_types.py

generate-build-stream-types:
    cd packages/backend && env -u VIRTUAL_ENV uv run python ../../scripts/generate_ts_build_stream_types.py

docker-dev:
    just generate-protocol
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build

docker-dev-down:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml down -v --remove-orphans

docker-dev-logs:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml logs -f

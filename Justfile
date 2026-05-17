# Data Forge task runner

default: dev

pytest := 'uv run python -m pytest -c pyproject.toml -q'
python := 'uv run python'

install:
    cd packages/shared && uv sync
    cd packages/backend && uv sync
    cd packages/scheduler && uv sync
    cd packages/worker-manager && uv sync
    cd packages/frontend && bun install

# Update dependencies to latest available versions
update-deps:
    @echo "Updating backend dependencies to latest..."
    cd packages/backend && uv lock --upgrade && uv sync
    @echo "Updating frontend dependencies to latest..."
    cd packages/frontend && bun update --latest
    @echo "Updating scheduler dependencies to latest..."
    cd packages/scheduler && uv lock --upgrade && uv sync
    @echo "Updating shared dependencies to latest..."
    cd packages/shared && uv lock --upgrade && uv sync
    @echo "Updating worker-manager dependencies to latest..."
    cd packages/worker-manager && uv lock --upgrade && uv sync

dev:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a; source packages/shared/dev.env; set +a
    (cd packages/backend && uv run --env-file ../shared/dev.env main.py) & \
    (cd packages/scheduler && uv run --env-file ../shared/dev.env main.py) & \
    (cd packages/worker-manager && uv run --env-file ../shared/dev.env main.py) & \
    (cd packages/frontend && bun run dev) & wait

dev-clean:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a; source packages/shared/dev.env; set +a
    cd packages/shared
    uv run python - <<'PY'
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from core.config import settings

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
    rm -rf .runtime/data packages/shared/data packages/shared/packages packages/backend/data packages/scheduler/data packages/worker-manager/data
    echo "✓ Local dev database and runtime data reset. Run 'just dev' to recreate everything."

format:
    cd packages/shared && uv run ruff check --select I --fix .
    cd packages/backend && uv run --project ../shared ruff check --select I --fix .
    cd packages/scheduler && uv run --project ../shared ruff check --select I --fix .
    cd packages/worker-manager && uv run --project ../shared ruff check --select I --fix .
    cd packages/shared && uv run ruff format .
    cd packages/backend && uv run --project ../shared ruff format .
    cd packages/scheduler && uv run --project ../shared ruff format .
    cd packages/worker-manager && uv run --project ../shared ruff format .
    cd packages/frontend && bun run format

check:
    cd packages/shared && uv run ruff format --check . ../backend ../scheduler ../worker-manager
    cd packages/shared && uv run ruff check . ../backend ../scheduler ../worker-manager
    cd packages/shared && uv run python -m mypy .
    cd packages/shared && uv run python -m mypy ../backend
    cd packages/shared && uv run python -m mypy ../scheduler
    cd packages/shared && uv run python -m mypy ../worker-manager
    cd packages/shared && uv run python ../../scripts/generate_ts_build_stream_types.py --check
    cd packages/shared && uv run python ../../scripts/generate_ts_step_types.py --check
    cd packages/shared && uv run python ../../scripts/check_package_boundaries.py
    cd packages/shared && uv run python ../../scripts/check_env_contracts.py
    cd packages/shared && uv run python ../../scripts/check_dependency_hygiene.py
    cd packages/shared && uv run python ../../scripts/check_code_hygiene.py
    cd packages/shared && uv run python ../../scripts/check_test_layout.py
    cd packages/frontend && bun run panda:codegen && bun run check && bun run lint

verify:
    cd packages/shared && uv run python ../../scripts/scan_warnings.py -- just format
    cd packages/shared && uv run python ../../scripts/scan_warnings.py -- just check


test:
    cd packages/shared && uv run python ../../scripts/scan_warnings.py -- just test-backend-raw
    cd packages/shared && uv run python ../../scripts/scan_warnings.py -- just test-frontend-raw

test-backend-raw:
    #!/usr/bin/env bash
    set -euo pipefail
    cd packages/shared
    {{pytest}} tests
    {{pytest}} ../backend/tests --ignore=../backend/tests/integration
    {{pytest}} ../backend/tests/integration
    {{pytest}} ../worker-manager/tests --ignore=../worker-manager/tests/integration
    {{pytest}} ../scheduler/tests

test-frontend-raw:
    cd packages/frontend && bun run test:unit

test-e2e:
    cd packages/shared && uv run python ../../scripts/scan_warnings.py --cwd . -- scripts/test_e2e.sh

generate-step-types:
    cd packages/shared && uv run python ../../scripts/generate_ts_step_types.py

generate-build-stream-types:
    cd packages/shared && uv run python ../../scripts/generate_ts_build_stream_types.py

docker-dev:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build

docker-dev-down:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml down -v --remove-orphans

docker-dev-logs:
    docker compose --env-file docker/env/dev.env -p dataforge-dev -f docker/docker-compose.yml -f docker/docker-compose.dev.yml logs -f

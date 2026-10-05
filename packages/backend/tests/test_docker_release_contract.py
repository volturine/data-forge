"""Contract tests for the Docker release topology and deployment standard."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / 'docker' / 'compose.yaml'
COMPOSE_E2E = ROOT / 'docker' / 'compose.e2e.yaml'
COMPOSE_DEV = ROOT / 'docker' / 'compose.dev.yaml'
PROD_ENV = ROOT / 'docker' / 'env' / 'prod.env'
DEV_ENV = ROOT / 'docker' / 'env' / 'dev.env'
DOCKERFILE = ROOT / 'docker' / 'Dockerfile'
JUSTFILE = ROOT / 'Justfile'
PUBLISH_WORKFLOW = ROOT / '.github' / 'workflows' / 'docker-publish.yml'


def test_single_production_compose_has_no_build_directive() -> None:
    text = COMPOSE.read_text()
    assert 'build:' not in text
    for service in ('postgres', 'api', 'runtime', 'worker', 'scheduler'):
        assert f'{service}:' in text
    assert 'image: ${DF_API_IMAGE}' in text
    assert 'image: ${DF_SCHEDULER_IMAGE}' in text
    assert 'image: ${DF_RUNTIME_IMAGE}' in text
    assert 'image: ${DF_WORKER_IMAGE}' in text


def test_compose_wires_worker_data_plane_across_containers() -> None:
    text = COMPOSE.read_text()
    assert 'WORKER_DATA_PLANE_GRPC_TARGET: worker:50052' in text
    worker_service = text.split('\n  worker:\n', 1)[1].split('\n  scheduler:\n', 1)[0]
    assert 'WORKER_DATA_PLANE_GRPC_HOST: 0.0.0.0' in worker_service
    assert 'WORKER_DATA_PLANE_GRPC_PORT: "50052"' in worker_service


def test_e2e_api_keep_alive_outlasts_the_suite_budget() -> None:
    """Playwright reuses API sockets until the server closes them.

    Uvicorn's 5s idle close races that pool and the next POST reads ECONNRESET
    with no response. The e2e API must keep idle sockets for the whole suite.
    """
    env_text = (ROOT / 'docker' / 'env' / 'e2e.env').read_text()
    suite = re.search(r'^E2E_TIMEOUT_SECONDS=\$\{E2E_TIMEOUT_SECONDS:-(\d+)\}', env_text, re.M)
    keep_alive = re.search(r'^UVICORN_TIMEOUT_KEEP_ALIVE=(\d+)\s*$', env_text, re.M)
    assert suite is not None and keep_alive is not None
    assert int(keep_alive.group(1)) >= int(suite.group(1))
    api_service = COMPOSE_E2E.read_text().split('\n  api:\n', 1)[1].split('\n  runtime:\n', 1)[0]
    assert 'UVICORN_TIMEOUT_KEEP_ALIVE: ${UVICORN_TIMEOUT_KEEP_ALIVE}' in api_service


def test_runtime_inherits_api_database_pool_settings_without_overrides() -> None:
    for compose in (COMPOSE, COMPOSE_E2E):
        text = compose.read_text()
        api_service = text.split('\n  api:\n', 1)[1].split('\n  runtime:\n', 1)[0]
        runtime_service = text.split('\n  runtime:\n', 1)[1].split('\n  worker:\n', 1)[0]

        assert 'environment: &api-env' in api_service
        assert 'DATABASE_POOL_SIZE:' in api_service
        assert 'DATABASE_MAX_OVERFLOW:' in api_service
        assert '<<: *api-env' in runtime_service
        assert 'DATABASE_POOL_SIZE:' not in runtime_service
        assert 'DATABASE_MAX_OVERFLOW:' not in runtime_service


def test_compose_services_define_relative_cpu_shares_without_changing_cpu_limits() -> None:
    expected = {
        'postgres': 2048,
        'api': 2048,
        'runtime': 2048,
        'worker': 2048,
        'scheduler': 1024,
        'rustfs': 512,
    }
    for compose in (COMPOSE, COMPOSE_E2E):
        text = compose.read_text()
        for service, shares in expected.items():
            service_match = re.search(rf'^  {re.escape(service)}:\n(.*?)(?=^  [\w-]+:\n|\Z)', text, re.M | re.S)
            assert service_match is not None
            assert f'cpu_shares: {shares}' in service_match.group(1)

    prod_text = COMPOSE.read_text()
    assert 'cpus: ${DF_API_CPUS:-0}' in prod_text
    assert 'cpus: ${DF_RUNTIME_CPUS:-0}' in prod_text
    assert 'cpus: ${DF_WORKER_CPUS:-0}' in prod_text

    e2e_text = COMPOSE_E2E.read_text()
    fixture_match = re.search(r'^  openai-fixture:\n(.*?)(?=^  [\w-]+:\n|\Z)', e2e_text, re.M | re.S)
    assert fixture_match is not None
    assert 'cpu_shares: 512' in fixture_match.group(1)

    dev_text = COMPOSE_DEV.read_text()
    frontend_match = re.search(r'^  frontend:\n(.*?)(?=^  [\w-]+:\n|\Z)', dev_text, re.M | re.S)
    assert frontend_match is not None
    assert 'cpu_shares: 512' in frontend_match.group(1)


def test_prod_env_uses_published_images_and_placeholder_secrets() -> None:
    text = PROD_ENV.read_text()
    assert 'DF_API_IMAGE=ghcr.io/volturine/data-forge-api:' in text
    assert 'DF_SCHEDULER_IMAGE=ghcr.io/volturine/data-forge-scheduler:' in text
    assert 'DF_RUNTIME_IMAGE=ghcr.io/volturine/data-forge-runtime:' in text
    assert 'DF_WORKER_IMAGE=ghcr.io/volturine/data-forge-worker:' in text
    assert 'replace-with-strong-password' in text
    assert 'replace-with-long-random-secret' in text
    assert 'replace-with-long-random-internal-runtime-token' in text


def test_prod_and_dev_stacks_do_not_collide() -> None:
    prod = PROD_ENV.read_text()
    dev = DEV_ENV.read_text()
    justfile = JUSTFILE.read_text()

    # Distinct compose project names.
    assert '-p dataforge-prod' in justfile
    assert '-p dataforge-dev' in justfile

    # Distinct per-stack engine networks driven by the env files.
    assert 'DF_ENGINE_DOCKER_NETWORK=dataforge-prod-engine-runtime' in prod
    assert 'DF_ENGINE_DOCKER_NETWORK=dataforge-dev-engine-runtime' in dev
    # And distinct from anything tests create (tests use ephemeral suffixes).
    assert 'dataforge-e2e' not in prod + dev

    # The production smoke stack must not bind the dev host port. It overrides
    # DF_API_PORT to a dedicated port instead of reusing the dev default 8000.
    assert 'DF_API_PORT="${DF_SMOKE_API_PORT:-8300}"' in justfile


def test_dockerfile_has_fixed_role_targets() -> None:
    text = DOCKERFILE.read_text()
    for target in ('AS api', 'AS scheduler', 'AS runtime', 'AS worker'):
        assert target in text
    assert 'HEALTHCHECK' in text
    assert 'org.opencontainers.image' in text


def test_just_docker_prod_overrides_only_image_tags() -> None:
    text = JUSTFILE.read_text()
    assert 'docker-prod:' in text
    assert 'docker/compose.yaml' in text
    assert 'docker/env/prod.env' in text
    assert 'DF_API_IMAGE=' in text
    assert 'DF_SCHEDULER_IMAGE=' in text
    assert 'DF_RUNTIME_IMAGE=' in text
    assert 'DF_WORKER_IMAGE=' in text
    assert 'data-forge-api:' in text
    assert 'data-forge-scheduler:' in text
    assert 'data-forge-runtime:' in text
    assert 'data-forge-worker:' in text


def test_publish_workflow_is_multi_arch_and_tag_triggered() -> None:
    text = PUBLISH_WORKFLOW.read_text()
    assert '"v*"' in text or "'v*'" in text
    assert 'linux/amd64,linux/arm64' in text
    assert 'data-forge-api' in text
    assert 'data-forge-scheduler' in text
    assert 'data-forge-runtime' in text
    assert 'ghcr.io' in text


def test_publish_workflow_publishes_dev_channel_images() -> None:
    """PRs and master feed the dev channel used by PR-preview deployments."""
    text = PUBLISH_WORKFLOW.read_text()
    assert 'pull_request' in text
    assert 'dev-pr-' in text
    assert 'dev-master' in text
    # Dev images are amd64-only, matching the central deployments preview stacks.
    assert 'platforms: linux/amd64\n' in text

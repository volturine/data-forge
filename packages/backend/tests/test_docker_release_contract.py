"""Contract tests for the Docker release topology and deployment standard."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / 'docker' / 'compose.yaml'
COMPOSE_DEV = ROOT / 'docker' / 'compose.dev.yaml'
PROD_ENV = ROOT / 'docker' / 'env' / 'prod.env'
DEV_ENV = ROOT / 'docker' / 'env' / 'dev.env'
DOCKERFILE = ROOT / 'docker' / 'Dockerfile'
JUSTFILE = ROOT / 'Justfile'
PUBLISH_WORKFLOW = ROOT / '.github' / 'workflows' / 'docker-publish.yml'


def test_single_production_compose_has_no_build_directive() -> None:
    text = COMPOSE.read_text()
    assert 'build:' not in text
    for service in ('postgres', 'api', 'scheduler', 'worker'):
        assert f'{service}:' in text
    assert 'image: ${DF_API_IMAGE}' in text
    assert 'image: ${DF_SCHEDULER_IMAGE}' in text
    assert 'image: ${DF_WORKER_IMAGE}' in text


def test_prod_env_uses_published_images_and_placeholder_secrets() -> None:
    text = PROD_ENV.read_text()
    assert 'DF_API_IMAGE=ghcr.io/volturine/data-forge-api:' in text
    assert 'DF_SCHEDULER_IMAGE=ghcr.io/volturine/data-forge-scheduler:' in text
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
    for target in ('AS api', 'AS scheduler', 'AS worker'):
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
    assert 'DF_WORKER_IMAGE=' in text
    assert 'data-forge-api:' in text
    assert 'data-forge-scheduler:' in text
    assert 'data-forge-worker:' in text


def test_publish_workflow_is_multi_arch_and_tag_triggered() -> None:
    text = PUBLISH_WORKFLOW.read_text()
    assert '"v*"' in text or "'v*'" in text
    assert 'linux/amd64,linux/arm64' in text
    assert 'data-forge-api' in text
    assert 'data-forge-scheduler' in text
    assert 'data-forge-worker' in text
    assert 'ghcr.io' in text


def test_publish_workflow_publishes_dev_channel_images() -> None:
    """PRs and master feed the dev channel used by PR-preview deployments."""
    text = PUBLISH_WORKFLOW.read_text()
    assert 'pull_request' in text
    assert 'dev-pr-' in text
    assert 'dev-master' in text
    # Dev images are amd64-only, matching the central deployments preview stacks.
    assert 'platforms: linux/amd64\n' in text

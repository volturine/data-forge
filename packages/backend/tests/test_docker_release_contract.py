"""Contract tests for the Docker production release topology."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / 'docker' / 'docker-compose.yml'
PROD_ENV = ROOT / 'docker' / 'env' / 'prod.env'
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


def test_dockerfile_has_fixed_role_targets() -> None:
    text = DOCKERFILE.read_text()
    for target in ('AS api', 'AS scheduler', 'AS worker'):
        assert target in text
    assert 'HEALTHCHECK' in text
    assert 'org.opencontainers.image' in text


def test_just_docker_prod_overrides_only_image_tags() -> None:
    text = JUSTFILE.read_text()
    assert 'docker-prod:' in text
    assert 'docker/docker-compose.yml' in text
    assert 'docker/env/prod.env' in text
    assert 'DF_API_IMAGE=' in text
    assert 'DF_SCHEDULER_IMAGE=' in text
    assert 'DF_WORKER_IMAGE=' in text
    assert 'data-forge-api:' in text
    assert 'data-forge-scheduler:' in text
    assert 'data-forge-worker:' in text


def test_publish_workflow_is_multi_arch_and_tag_triggered() -> None:
    text = PUBLISH_WORKFLOW.read_text()
    assert 'tags:' in text
    assert '"v*"' in text or "'v*'" in text
    assert 'linux/amd64,linux/arm64' in text
    assert 'data-forge-api' in text
    assert 'data-forge-scheduler' in text
    assert 'data-forge-worker' in text
    assert 'ghcr.io' in text

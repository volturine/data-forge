import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, select

from backend_core.domain.analysis.models import AnalysisStatus
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.analysis_versions.models import AnalysisVersion
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.locks.models import ResourceLock
from backend_core.sqlmodel_typing import col
from modules.analysis_versions.service import create_version, get_version, restore_version
from tests.harness.analysis_payloads import tab_payload
from tests.http_client import TestClient


@pytest.fixture(autouse=True)
def _use_current_analysis_revision(client: TestClient) -> None:
    client.headers['If-Match'] = '1'


def test_list_versions_returns_versions(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Versioned Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-1',
        analysis_id=analysis_id,
        version=1,
        name='Versioned Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.get(f'/api/v1/analysis/{analysis_id}/versions')

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['version'] == 1


def test_restore_version_updates_analysis(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    analysis_pipeline: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Original',
        description=None,
        pipeline_definition=analysis_pipeline,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-2',
        analysis_id=analysis_id,
        version=2,
        name='Restored',
        description='restored',
        pipeline_definition={
            'steps': [{'id': 'step-1', 'type': 'select', 'config': {}}],
            'tabs': [
                tab_payload(sample_datasource.id, tab_id='tab-1'),
            ],
        },
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/2/restore')

    assert response.status_code == 200
    payload = response.json()
    assert payload['name'] == 'Restored'


def test_restore_version_rejects_when_analysis_locked_by_other_owner(
    test_db_session,
    client,
    sample_datasource: DataSource,
    monkeypatch,
):
    monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
    analysis_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    analysis_pipeline: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Original',
        description=None,
        pipeline_definition=analysis_pipeline,
        status=AnalysisStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
    version = AnalysisVersion(
        id='version-locked-restore',
        analysis_id=analysis_id,
        version=1,
        name='Locked Restore',
        description=None,
        pipeline_definition=analysis_pipeline,
        created_at=now,
    )
    lock = ResourceLock(
        resource_type='analysis',
        resource_id=analysis_id,
        owner_id='other-owner',
        lock_token='locked-token',
        acquired_at=now.replace(tzinfo=None),
        expires_at=(now + timedelta(minutes=5)).replace(tzinfo=None),
        last_heartbeat=now.replace(tzinfo=None),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.add(lock)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 409
    assert response.json()['detail'] == f'analysis {analysis_id} is locked by another owner'


def test_rename_version(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Rename Test',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-rename-1',
        analysis_id=analysis_id,
        version=1,
        name='Original Name',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.patch(
        f'/api/v1/analysis/{analysis_id}/versions/1',
        json={'name': 'Renamed Version'},
    )

    assert response.status_code == 200
    data = response.json()
    assert data['name'] == 'Renamed Version'
    assert data['version'] == 1


def test_rename_version_not_found(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Not Found Test',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.commit()

    response = client.patch(
        f'/api/v1/analysis/{analysis_id}/versions/999',
        json={'name': 'Does Not Exist'},
    )

    assert response.status_code == 404


def test_create_version_increments(test_db_session, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Versioned Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.commit()

    first = create_version(test_db_session, analysis)
    second = create_version(test_db_session, analysis)

    assert second.version == first.version + 1


def test_get_version_returns_none(test_db_session, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Missing Version',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.commit()

    result = get_version(test_db_session, analysis_id, 99)
    assert result is None


def test_restore_version_cycle_detection(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    cycle_id = str(uuid.uuid4())
    cycle_ds = DataSource(
        id=cycle_id,
        name='Cycle Source',
        source_type=DataSourceType.ANALYSIS,
        config={
            'analysis_tab_id': 'tab-1',
        },
        created_by='analysis',
        created_by_analysis_id=analysis_id,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(cycle_ds)
    pipeline_definition: dict[str, Any] = {
        'steps': [],
        'tabs': [
            tab_payload(cycle_id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Cycle Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-cycle-1',
        analysis_id=analysis_id,
        version=1,
        name='Cycle Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 422
    assert 'analysis cannot use itself' in response.json()['detail'].lower()


def test_restore_version_requires_datasource(test_db_session: Session, client: TestClient) -> None:
    analysis_id = str(uuid.uuid4())
    missing_ds_id = str(uuid.uuid4())
    pipeline_definition: dict[str, object] = {
        'steps': [],
        'tabs': [
            tab_payload(missing_ds_id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Missing Datasource',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-missing-ds',
        analysis_id=analysis_id,
        version=1,
        name='Missing Datasource',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 404
    assert 'datasource' in response.json()['detail'].lower()


def test_restore_version_rejects_missing_branch(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    pipeline_definition: dict[str, object] = {
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1', datasource_config={}),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Missing Branch',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-missing-branch',
        analysis_id=analysis_id,
        version=1,
        name='Missing Branch',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 400
    assert 'tabs.0.datasource.config.branch' in response.json()['detail'].lower()


def test_restore_version_relinks_analysis_datasource(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    datasource = DataSource(
        id=source_id,
        name='Source',
        source_type=DataSourceType.ANALYSIS,
        config={'analysis_tab_id': 'tab-1'},
        created_by='analysis',
        created_by_analysis_id='source-analysis',
        created_at=datetime.now(UTC),
    )
    pipeline_definition = {
        'steps': [],
        'tabs': [
            tab_payload(source_id, tab_id='tab-1'),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Relink Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-relink',
        analysis_id=analysis_id,
        version=1,
        name='Relink Analysis',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 200


def test_restore_version_with_derived_tab_uses_internal_output_mapping(test_db_session, client, sample_datasource: DataSource):
    analysis_id = str(uuid.uuid4())
    output_id = str(uuid.uuid4())
    derived_output_id = str(uuid.uuid4())
    pipeline_definition = {
        'steps': [],
        'tabs': [
            tab_payload(sample_datasource.id, tab_id='tab-1', result_id=output_id),
            tab_payload(
                output_id,
                tab_id='tab-2',
                name='Derived',
                parent_id='tab-1',
                analysis_tab_id='tab-1',
                result_id=derived_output_id,
                filename='derived_output',
            ),
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Derived Restore',
        description=None,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-restore-derived',
        analysis_id=analysis_id,
        version=1,
        name='Derived Restore',
        description=None,
        pipeline_definition=pipeline_definition,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/1/restore')

    assert response.status_code == 200
    output_ds = test_db_session.get(DataSource, output_id)
    assert output_ds is None


def test_restore_does_not_alias_version_pipeline(test_db_session, sample_datasource: DataSource):
    """Restoring a version must deep-copy: mutating the analysis afterwards
    must never corrupt the restored version row's stored definition.
    """
    analysis_id = str(uuid.uuid4())

    def _pipeline(name: str) -> dict[str, Any]:
        return {
            'steps': [],
            'tabs': [
                tab_payload(sample_datasource.id, tab_id='tab-1', name=name),
            ],
        }

    analysis = Analysis(
        id=analysis_id,
        name='Aliasing Analysis',
        description=None,
        pipeline_definition=_pipeline('Current'),
        status=AnalysisStatus.DRAFT,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    create_version(test_db_session, analysis)
    analysis.pipeline_definition = _pipeline('Mutated')
    analysis.revision += 1
    test_db_session.add(analysis)
    test_db_session.commit()

    restore_version(test_db_session, analysis_id, 1)

    reloaded_analysis = test_db_session.get(Analysis, analysis_id)
    version_rows = sorted(
        (v.version, v) for v in test_db_session.execute(select(AnalysisVersion).where(col(AnalysisVersion.analysis_id) == analysis_id)).scalars()
    )
    assert reloaded_analysis is not None
    assert reloaded_analysis.pipeline_definition['tabs'][0]['name'] == 'Current'
    assert version_rows[0][1].pipeline_definition['tabs'][0]['name'] == 'Current'

    # In-place mutation of the live analysis must stay isolated from history.
    reloaded_analysis.pipeline_definition['tabs'][0]['name'] = 'Mutated Again'
    test_db_session.add(reloaded_analysis)
    test_db_session.commit()
    test_db_session.expire_all()
    final_version = get_version(test_db_session, analysis_id, 2)
    assert final_version is not None
    assert final_version.pipeline_definition['tabs'][0]['name'] == 'Mutated'

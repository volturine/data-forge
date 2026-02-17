import uuid
from datetime import UTC, datetime

from modules.analysis.models import Analysis
from modules.analysis_versions.models import AnalysisVersion
from modules.analysis_versions.service import create_version, get_version
from modules.datasource.models import DataSource


def test_list_versions_returns_versions(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Versioned Analysis',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-1',
        analysis_id=analysis_id,
        version=1,
        name='Versioned Analysis',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
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


def test_restore_version_updates_analysis(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Original',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-2',
        analysis_id=analysis_id,
        version=2,
        name='Restored',
        description='restored',
        pipeline_definition={'steps': [{'id': 'step-1', 'type': 'select', 'config': {}}], 'datasource_ids': [], 'tabs': []},
        created_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.add(version)
    test_db_session.commit()

    response = client.post(f'/api/v1/analysis/{analysis_id}/versions/2/restore')

    assert response.status_code == 200
    payload = response.json()
    assert payload['name'] == 'Restored'


def test_rename_version(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Rename Test',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    version = AnalysisVersion(
        id='version-rename-1',
        analysis_id=analysis_id,
        version=1,
        name='Original Name',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
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


def test_rename_version_not_found(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Not Found Test',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
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


def test_create_version_increments(test_db_session):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Versioned Analysis',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.commit()

    first = create_version(test_db_session, analysis)
    second = create_version(test_db_session, analysis)

    assert second.version == first.version + 1


def test_get_version_returns_none(test_db_session):
    analysis_id = str(uuid.uuid4())
    analysis = Analysis(
        id=analysis_id,
        name='Missing Version',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    test_db_session.add(analysis)
    test_db_session.commit()

    result = get_version(test_db_session, analysis_id, 99)
    assert result is None


def test_restore_version_cycle_detection(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    pipeline_definition = {
        'steps': [],
        'datasource_ids': [],
        'tabs': [
            {
                'id': 'tab-1',
                'name': 'Source',
                'type': 'datasource',
                'datasource_id': None,
                'datasource_config': {
                    'analysis_id': analysis_id,
                },
            }
        ],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Cycle Analysis',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
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

    assert response.status_code == 404
    assert 'analysis cannot use itself' in response.json()['detail'].lower()


def test_restore_version_requires_datasource(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    missing_ds_id = str(uuid.uuid4())
    pipeline_definition = {
        'steps': [],
        'datasource_ids': [missing_ds_id],
        'tabs': [],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Missing Datasource',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
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


def test_restore_version_relinks_analysis_datasource(test_db_session, client):
    analysis_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    datasource = DataSource(
        id=source_id,
        name='Source',
        source_type='analysis',
        config={'analysis_id': 'source-analysis'},
        created_by='analysis',
        created_by_analysis_id='source-analysis',
        created_at=datetime.now(UTC),
    )
    pipeline_definition = {
        'steps': [],
        'datasource_ids': [source_id],
        'tabs': [],
    }
    analysis = Analysis(
        id=analysis_id,
        name='Relink Analysis',
        description=None,
        pipeline_definition={'steps': [], 'datasource_ids': [], 'tabs': []},
        status='draft',
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

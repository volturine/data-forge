import uuid
from datetime import UTC, datetime, timedelta

from modules.datasource.models import DataSource
from modules.healthcheck.models import HealthCheck, HealthCheckResult


def _create_datasource(session, ds_id: str = 'ds-health-1') -> DataSource:
    datasource = DataSource(
        id=ds_id,
        name='Health Source',
        source_type='file',
        config={'file_path': '/tmp/file.csv', 'file_type': 'csv', 'options': {}},
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    return datasource


def _create_check(session, datasource_id: str, name: str = 'Row Count Check') -> HealthCheck:
    check = HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=datasource_id,
        name=name,
        check_type='row_count',
        config={'min_rows': 1},
        enabled=True,
        created_at=datetime.now(UTC),
    )
    session.add(check)
    session.commit()
    session.refresh(check)
    return check


def _create_result(session, healthcheck_id: str, passed: bool, message: str, minutes_ago: int = 0) -> HealthCheckResult:
    result = HealthCheckResult(
        id=str(uuid.uuid4()),
        healthcheck_id=healthcheck_id,
        passed=passed,
        message=message,
        details={'min_rows': 1},
        checked_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def test_healthcheck_crud(test_db_session, client):
    datasource_id = 'ds-health-1'
    _create_datasource(test_db_session, datasource_id)

    create_payload = {
        'datasource_id': datasource_id,
        'name': 'Row Count Check',
        'check_type': 'row_count',
        'config': {'min_rows': 1},
        'enabled': True,
    }
    create_response = client.post('/api/v1/healthchecks', json=create_payload)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['name'] == 'Row Count Check'

    list_response = client.get(f'/api/v1/healthchecks?datasource_id={datasource_id}')
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1

    update_response = client.put(
        f'/api/v1/healthchecks/{created["id"]}',
        json={'name': 'Updated Check', 'enabled': False},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated['name'] == 'Updated Check'
    assert updated['enabled'] is False

    delete_response = client.delete(f'/api/v1/healthchecks/{created["id"]}')
    assert delete_response.status_code == 200


def test_list_results_empty(test_db_session, client):
    """No results returns empty list."""
    datasource_id = 'ds-results-empty'
    _create_datasource(test_db_session, datasource_id)
    _create_check(test_db_session, datasource_id)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    assert response.json() == []


def test_list_results_after_run(test_db_session, client):
    """Results are returned after inserting a HealthCheckResult."""
    datasource_id = 'ds-results-run'
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)
    _create_result(test_db_session, check.id, True, 'Row count: 42')

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['healthcheck_id'] == check.id
    assert data[0]['passed'] is True
    assert data[0]['message'] == 'Row count: 42'


def test_list_results_limit(test_db_session, client):
    """Limit parameter restricts number of returned results."""
    datasource_id = 'ds-results-limit'
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    for i in range(5):
        _create_result(test_db_session, check.id, True, f'Result {i}', minutes_ago=i)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}&limit=3')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_list_results_ordering(test_db_session, client):
    """Results are ordered by checked_at DESC (most recent first)."""
    datasource_id = 'ds-results-order'
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    _create_result(test_db_session, check.id, False, 'Old failure', minutes_ago=10)
    _create_result(test_db_session, check.id, True, 'Recent success', minutes_ago=0)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]['message'] == 'Recent success'
    assert data[1]['message'] == 'Old failure'


def test_list_results_no_datasource(client):
    """Results for non-existent datasource returns empty list."""
    response = client.get('/api/v1/healthchecks/results?datasource_id=nonexistent')
    assert response.status_code == 200
    assert response.json() == []

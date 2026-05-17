import uuid
from datetime import UTC, datetime, timedelta

from contracts.datasource.models import DataSource
from contracts.healthcheck_models import HealthCheck, HealthCheckResult


def _create_datasource(session, ds_id: str | None = None) -> DataSource:
    datasource = DataSource(
        id=ds_id or str(uuid.uuid4()),
        name="Datasource",
        description="fixture",
        source_type="file",
        config={"file_path": "/tmp/file.csv", "file_type": "csv", "options": {}},
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return datasource


def _create_check(session, datasource_id: str, name: str = "Row Count Check") -> HealthCheck:
    check = HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=datasource_id,
        name=name,
        check_type="row_count",
        config={"min_rows": 1},
        enabled=True,
        critical=False,
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
        details={"min_rows": 1},
        checked_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def test_healthcheck_crud(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)

    create_payload = {
        "datasource_id": datasource_id,
        "name": "Row Count Check",
        "check_type": "row_count",
        "config": {"min_rows": 1},
        "enabled": True,
        "critical": True,
    }
    create_response = client.post("/api/v1/healthchecks", json=create_payload)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["name"] == "Row Count Check"
    assert created["critical"] is True

    duplicate_response = client.post("/api/v1/healthchecks", json=create_payload)
    assert duplicate_response.status_code == 400

    list_response = client.get(f"/api/v1/healthchecks?datasource_id={datasource_id}")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = client.put(
        f"/api/v1/healthchecks/{created['id']}",
        json={"name": "Updated Check", "enabled": False, "critical": False},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["name"] == "Updated Check"
    assert updated["enabled"] is False
    assert updated["critical"] is False

    delete_response = client.delete(f"/api/v1/healthchecks/{created['id']}")
    assert delete_response.status_code == 204


def test_healthcheck_update_duplicate_row_count(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)

    first_payload = {
        "datasource_id": datasource_id,
        "name": "Row Count Check",
        "check_type": "row_count",
        "config": {"min_rows": 1},
        "enabled": True,
        "critical": False,
    }
    first_response = client.post("/api/v1/healthchecks", json=first_payload)
    assert first_response.status_code == 200
    second_id = str(uuid.uuid4())
    test_db_session.add(
        HealthCheck(
            id=second_id,
            datasource_id=datasource_id,
            name="Column Null Check",
            check_type="column_null",
            config={"column": "name", "threshold": 10},
            enabled=True,
            critical=False,
            created_at=datetime.now(UTC),
        ),
    )
    test_db_session.commit()

    update_response = client.put(
        f"/api/v1/healthchecks/{second_id}",
        json={"check_type": "row_count"},
    )
    assert update_response.status_code == 400


def test_list_healthchecks_all_datasources(test_db_session, client):
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    _create_datasource(test_db_session, first_id)
    _create_datasource(test_db_session, second_id)
    first = _create_check(test_db_session, first_id, name="First Check")
    second = _create_check(test_db_session, second_id, name="Second Check")

    response = client.get("/api/v1/healthchecks/all")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert ids == {first.id, second.id}


def test_list_healthchecks_requires_datasource_id(client):
    response = client.get("/api/v1/healthchecks")
    assert response.status_code == 422


def test_list_results_empty(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    _create_check(test_db_session, datasource_id)

    response = client.get(f"/api/v1/healthchecks/results?datasource_id={datasource_id}")
    assert response.status_code == 200
    assert response.json() == []


def test_list_results_after_run(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)
    _create_result(test_db_session, check.id, True, "Row count: 42")

    response = client.get(f"/api/v1/healthchecks/results?datasource_id={datasource_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["healthcheck_id"] == check.id
    assert data[0]["passed"] is True
    assert data[0]["message"] == "Row count: 42"


def test_list_results_limit(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    for i in range(5):
        _create_result(test_db_session, check.id, True, f"Result {i}", minutes_ago=i)

    response = client.get(f"/api/v1/healthchecks/results?datasource_id={datasource_id}&limit=3")
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_results_all_datasources_limit(test_db_session, client):
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    _create_datasource(test_db_session, first_id)
    _create_datasource(test_db_session, second_id)
    first = _create_check(test_db_session, first_id, name="First Check")
    second = _create_check(test_db_session, second_id, name="Second Check")

    _create_result(test_db_session, first.id, True, "First recent", minutes_ago=0)
    _create_result(test_db_session, second.id, False, "Second recent", minutes_ago=1)
    _create_result(test_db_session, first.id, True, "First older", minutes_ago=2)
    _create_result(test_db_session, second.id, False, "Second older", minutes_ago=3)

    response = client.get("/api/v1/healthchecks/results/all?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert [item["message"] for item in data] == [
        "First recent",
        "Second recent",
        "First older",
    ]


def test_list_results_ordering(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    _create_result(test_db_session, check.id, False, "Old failure", minutes_ago=10)
    _create_result(test_db_session, check.id, True, "Recent success", minutes_ago=0)

    response = client.get(f"/api/v1/healthchecks/results?datasource_id={datasource_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["message"] == "Recent success"
    assert data[1]["message"] == "Old failure"


def test_list_results_requires_datasource_id(client):
    response = client.get("/api/v1/healthchecks/results")
    assert response.status_code == 422


def test_list_results_missing_datasource(client):
    missing_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/healthchecks/results?datasource_id={missing_id}")
    assert response.status_code == 200
    assert response.json() == []


def test_list_results_invalid_uuid(client):
    response = client.get("/api/v1/healthchecks/results?datasource_id=nonexistent")
    assert response.status_code == 400

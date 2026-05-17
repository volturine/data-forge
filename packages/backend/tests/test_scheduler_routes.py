import uuid
from datetime import UTC, datetime

import pytest
from contracts.analysis.models import Analysis
from contracts.datasource.models import DataSource
from sqlmodel import Session


@pytest.fixture(scope="function")
def output_datasource(test_db_session: Session, sample_analysis: Analysis) -> DataSource:
    datasource = DataSource(
        id=str(uuid.uuid4()),
        name="Output DataSource",
        source_type="iceberg",
        config={"analysis_tab_id": "tab1"},
        created_by="analysis",
        created_by_analysis_id=sample_analysis.id,
        is_hidden=True,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(datasource)
    test_db_session.commit()
    test_db_session.refresh(datasource)
    return datasource


class TestScheduleRoutes:
    def test_list_empty(self, client):
        response = client.get("/api/v1/schedules")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_and_list(self, client, output_datasource: DataSource, sample_analysis: Analysis):
        payload = {
            "datasource_id": output_datasource.id,
            "cron_expression": "0 * * * *",
        }
        response = client.post("/api/v1/schedules", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["datasource_id"] == output_datasource.id
        assert data["analysis_id"] == sample_analysis.id
        assert data["analysis_name"] == sample_analysis.name
        assert data["cron_expression"] == "0 * * * *"
        assert data["enabled"] is True

        response = client.get("/api/v1/schedules")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_filtered_by_datasource(self, client, sample_analyses: list[Analysis], test_db_session: Session):
        a1, a2, _ = sample_analyses
        ds1 = DataSource(
            id=str(uuid.uuid4()),
            name="Output 1",
            source_type="iceberg",
            config={"analysis_tab_id": "tab1"},
            created_by="analysis",
            created_by_analysis_id=a1.id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        ds2 = DataSource(
            id=str(uuid.uuid4()),
            name="Output 2",
            source_type="iceberg",
            config={"analysis_tab_id": "tab1"},
            created_by="analysis",
            created_by_analysis_id=a2.id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds1)
        test_db_session.add(ds2)
        test_db_session.commit()

        client.post(
            "/api/v1/schedules",
            json={"datasource_id": ds1.id, "cron_expression": "0 * * * *"},
        )
        client.post(
            "/api/v1/schedules",
            json={"datasource_id": ds2.id, "cron_expression": "0 0 * * *"},
        )

        response = client.get(f"/api/v1/schedules?datasource_id={ds1.id}")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_update(self, client, output_datasource: DataSource):
        create_resp = client.post(
            "/api/v1/schedules",
            json={
                "datasource_id": output_datasource.id,
                "cron_expression": "0 * * * *",
            },
        )
        schedule_id = create_resp.json()["id"]

        response = client.put(f"/api/v1/schedules/{schedule_id}", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    def test_update_nonexistent_404(self, client):
        missing_id = str(uuid.uuid4())
        response = client.put(f"/api/v1/schedules/{missing_id}", json={"enabled": False})
        assert response.status_code == 404

    def test_delete(self, client, output_datasource: DataSource):
        create_resp = client.post(
            "/api/v1/schedules",
            json={
                "datasource_id": output_datasource.id,
                "cron_expression": "0 * * * *",
            },
        )
        schedule_id = create_resp.json()["id"]

        response = client.delete(f"/api/v1/schedules/{schedule_id}")
        assert response.status_code == 204

        response = client.get("/api/v1/schedules")
        assert len(response.json()) == 0

    def test_delete_nonexistent_404(self, client):
        missing_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/schedules/{missing_id}")
        assert response.status_code == 404

    def test_create_allows_non_analysis_datasource(self, client, sample_datasource: DataSource):
        payload = {
            "datasource_id": sample_datasource.id,
            "cron_expression": "0 * * * *",
        }
        response = client.post("/api/v1/schedules", json=payload)
        assert response.status_code == 200

    def test_create_allows_reingestable_raw_iceberg(self, client, test_db_session: Session, sample_csv_file):
        raw = DataSource(
            id=str(uuid.uuid4()),
            name="Raw Iceberg",
            source_type="iceberg",
            config={
                "metadata_path": "/tmp/path",
                "branch": "master",
                "source": {
                    "source_type": "file",
                    "file_path": str(sample_csv_file),
                    "file_type": "csv",
                    "options": {},
                },
            },
            created_by="import",
            created_at=datetime.now(UTC),
        )
        test_db_session.add(raw)
        test_db_session.commit()

        payload = {"datasource_id": raw.id, "cron_expression": "0 * * * *"}
        response = client.post("/api/v1/schedules", json=payload)
        assert response.status_code == 200

    def test_create_rejected_for_nonexistent_datasource(self, client):
        payload = {
            "datasource_id": str(uuid.uuid4()),
            "cron_expression": "0 * * * *",
        }
        response = client.post("/api/v1/schedules", json=payload)
        assert response.status_code == 404

    def test_list_filtered_by_datasource_id(
        self,
        client,
        test_db_session: Session,
        sample_analysis: Analysis,
        output_datasource: DataSource,
    ):
        ds_id = output_datasource.id
        ds2 = DataSource(
            id=str(uuid.uuid4()),
            name="Output DataSource 2",
            source_type="iceberg",
            config={"analysis_tab_id": "tab1"},
            created_by="analysis",
            created_by_analysis_id=sample_analysis.id,
            is_hidden=True,
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds2)
        test_db_session.commit()
        other_ds_id = ds2.id
        client.post(
            "/api/v1/schedules",
            json={"datasource_id": ds_id, "cron_expression": "0 * * * *"},
        )
        client.post(
            "/api/v1/schedules",
            json={"datasource_id": other_ds_id, "cron_expression": "0 0 * * *"},
        )

        response = client.get(f"/api/v1/schedules?datasource_id={ds_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["datasource_id"] == ds_id

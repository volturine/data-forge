import uuid

from contracts.analysis.models import AnalysisDataSource
from contracts.datasource.models import DataSource
from sqlalchemy import select


class TestAnalysisDatasourceDedupe:
    def test_duplicate_datasource_across_tabs_inserts_one_row(self, client, sample_datasource: DataSource, test_db_session):
        shared_id = sample_datasource.id
        payload = {
            "name": "Dedup Test",
            "description": "",
            "tabs": [
                {
                    "id": "tab1",
                    "name": "Tab 1",
                    "parent_id": None,
                    "datasource": {
                        "id": shared_id,
                        "analysis_tab_id": None,
                        "config": {"branch": "master"},
                    },
                    "output": {
                        "result_id": str(uuid.uuid4()),
                        "format": "parquet",
                        "filename": "out1",
                    },
                    "steps": [],
                },
                {
                    "id": "tab2",
                    "name": "Tab 2",
                    "parent_id": None,
                    "datasource": {
                        "id": shared_id,
                        "analysis_tab_id": None,
                        "config": {"branch": "master"},
                    },
                    "output": {
                        "result_id": str(uuid.uuid4()),
                        "format": "parquet",
                        "filename": "out2",
                    },
                    "steps": [],
                },
            ],
        }
        response = client.post("/api/v1/analysis", json=payload)
        assert response.status_code == 200
        analysis_id = response.json()["id"]
        rows = test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)).scalars().all()
        assert len(rows) == 1
        assert rows[0].datasource_id == shared_id

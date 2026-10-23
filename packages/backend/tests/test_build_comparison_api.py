from sqlmodel import Session

from tests.harness.compute_run_factories import create_compute_worker_run


class TestCompareEndpoint:
    def test_compare_endpoint(self, client, test_db_session: Session) -> None:
        run_a = create_compute_worker_run(
            test_db_session,
            result_json={'schema': {'x': 'Int64'}, 'row_count': 10},
            step_timings={'s1': 50},
            duration_ms=50,
        )
        run_b = create_compute_worker_run(
            test_db_session,
            analysis_id=run_a.analysis_id,
            datasource_id=run_a.datasource_id,
            result_json={'schema': {'x': 'Int64', 'y': 'Utf8'}, 'row_count': 20},
            step_timings={'s1': 60},
            duration_ms=60,
        )

        resp = client.get(
            '/api/v1/compute-worker-runs/compare',
            params={'run_a': run_a.id, 'run_b': run_b.id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['row_count_a'] == 10
        assert data['row_count_b'] == 20
        assert data['row_count_delta'] == 10
        assert data['total_duration_delta_ms'] == 10
        assert len(data['schema_diff']) == 1
        assert data['schema_diff'][0]['column'] == 'y'
        assert data['schema_diff'][0]['status'] == 'added'

    def test_compare_endpoint_not_found(self, client) -> None:
        resp = client.get(
            '/api/v1/compute-worker-runs/compare',
            params={'run_a': 'fake-a', 'run_b': 'fake-b'},
        )
        assert resp.status_code == 400

    def test_compare_endpoint_datasource_mismatch(self, client, test_db_session: Session) -> None:
        run_a = create_compute_worker_run(test_db_session, result_json={'row_count': 10})
        run_b = create_compute_worker_run(test_db_session, result_json={'row_count': 20})
        resp = client.get(
            '/api/v1/compute-worker-runs/compare',
            params={
                'run_a': run_a.id,
                'run_b': run_b.id,
                'datasource_id': run_a.datasource_id,
            },
        )
        assert resp.status_code == 400

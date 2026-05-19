from datetime import UTC, datetime
from typing import Any

from contracts.datasource.models import DataSource
from contracts.datasource.source_types import DataSourceType

from modules.datasource import routes


class _AvailableRuntimeProbe:
    @staticmethod
    def available(*, kind) -> bool:
        del kind
        return True


async def _create_database_datasource_stub(
    session,
    *,
    name: str,
    description: str | None,
    connection_string: str,
    query: str,
    branch: str,
    owner_id: str | None = None,
    **kwargs: Any,
):
    del kwargs
    datasource = DataSource(
        id="internal-ds-1",
        name=name,
        description=description,
        source_type=DataSourceType.DATABASE.value,
        config={"connection_string": connection_string, "query": query, "branch": branch},
        owner_id=owner_id,
        created_by="import",
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    session.refresh(datasource)
    return datasource


def test_list_internal_postgres_tables_reports_application_tables(client, test_db_session) -> None:
    del test_db_session

    response = client.get("/api/v1/datasource/internal-postgres/tables")

    assert response.status_code == 200
    rows = response.json()
    names = {(row["schema_name"], row["table_name"]) for row in rows}
    assert ("default", "analyses") in names
    row = next(row for row in rows if row["schema_name"] == "default" and row["table_name"] == "analyses")
    assert row["is_onboarded"] is False


def test_toggle_internal_postgres_table_creates_database_datasource_once_and_deletes_on_disable(
    client,
    monkeypatch,
    test_db_session,
) -> None:
    calls = 0

    async def _stub(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await _create_database_datasource_stub(*args, **kwargs)

    monkeypatch.setattr(routes, "create_remote_database_datasource", _stub)

    enabled = client.post(
        "/api/v1/datasource/internal-postgres/toggle",
        json={"schema_name": "default", "table_name": "analyses", "enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {
        "schema_name": "default",
        "table_name": "analyses",
        "is_onboarded": True,
    }
    assert calls == 1

    enabled_again = client.post(
        "/api/v1/datasource/internal-postgres/toggle",
        json={"schema_name": "default", "table_name": "analyses", "enabled": True},
    )
    assert enabled_again.status_code == 200
    assert enabled_again.json()["is_onboarded"] is True
    assert calls == 1

    listed = client.get("/api/v1/datasource/internal-postgres/tables")
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["schema_name"] == "default" and item["table_name"] == "analyses")
    assert row["is_onboarded"] is True
    assert test_db_session.get(DataSource, "internal-ds-1") is not None

    disabled = client.post(
        "/api/v1/datasource/internal-postgres/toggle",
        json={"schema_name": "default", "table_name": "analyses", "enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {
        "schema_name": "default",
        "table_name": "analyses",
        "is_onboarded": False,
    }
    assert test_db_session.get(DataSource, "internal-ds-1") is None

    relisted = client.get("/api/v1/datasource/internal-postgres/tables")
    assert relisted.status_code == 200
    row = next(item for item in relisted.json() if item["schema_name"] == "default" and item["table_name"] == "analyses")
    assert row["is_onboarded"] is False

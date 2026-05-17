import json
from datetime import UTC, datetime

from modules.logs import service as logs_service
from modules.logs.schemas import ClientLogField, ClientLogItem


class _Writer:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def write_client_logs(self, payloads: list[dict]) -> None:
        self.payloads.extend(payloads)


def test_client_log_item_owns_request_context_and_payload() -> None:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    item = ClientLogItem(
        event="click",
        action="submit",
        fields=[ClientLogField(name="email", value="user@example.com", redacted=True)],
        meta={"page": "settings"},
    )

    updated = item.with_request_context(client_id="client-1", session_id="session-1")
    payload = updated.to_log_payload(now=stamp)

    assert updated.client_id == "client-1"
    assert updated.session_id == "session-1"
    assert payload["ts"] == stamp
    assert json.loads(payload["fields_json"]) == [{"name": "email", "value": "user@example.com", "redacted": True}]
    assert json.loads(payload["meta_json"]) == {"page": "settings"}


def test_save_client_logs_delegates_to_item_payloads(monkeypatch) -> None:
    writer = _Writer()
    monkeypatch.setattr(logs_service, "get_log_writer", lambda: writer)

    total = logs_service.save_client_logs(
        [
            ClientLogItem(
                event="view",
                page="/profile",
                client_id="client-2",
                session_id="session-2",
            )
        ]
    )

    assert total == 1
    assert writer.payloads[0]["event"] == "view"
    assert writer.payloads[0]["client_id"] == "client-2"
    assert writer.payloads[0]["session_id"] == "session-2"
    assert writer.payloads[0]["ts"].tzinfo is not None


def test_ingest_client_logs_uses_request_headers_as_context(client, monkeypatch) -> None:
    captured: dict[str, list[ClientLogItem]] = {}

    def fake_save(items: list[ClientLogItem]) -> int:
        captured["items"] = items
        return len(items)

    monkeypatch.setattr("modules.logs.routes.save_client_logs", fake_save)

    response = client.post(
        "/api/v1/logs/client",
        json={"logs": [{"event": "click", "fields": []}]},
        headers={"x-client-id": "header-client", "x-client-session": "header-session"},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert captured["items"][0].client_id == "header-client"
    assert captured["items"][0].session_id == "header-session"

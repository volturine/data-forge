import pytest

from runtime import runtime_notifications
from runtime.datasource_delete_runtime import datasource_delete_hub
from runtime.domain.compute_requests.live import ComputeRequestWake, request_hub
from runtime.domain.runtime.events import RuntimePayloadKind


@pytest.mark.asyncio
async def test_datasource_delete_notification_wakes_target_namespace() -> None:
    await datasource_delete_hub.clear()
    previous_version = datasource_delete_hub.version()

    await runtime_notifications.handle_runtime_payload(
        {
            "kind": RuntimePayloadKind.DATASOURCE_DELETE.value,
            "namespace": "tenant-a",
            "datasource_id": "datasource-1",
        }
    )

    assert datasource_delete_hub.version() == previous_version + 1
    assert datasource_delete_hub.payloads_since(previous_version) == ["tenant-a"]


@pytest.mark.asyncio
async def test_compute_request_notification_preserves_request_identity_and_kind() -> None:
    await request_hub.clear()
    previous_version = request_hub.version()

    await runtime_notifications.handle_runtime_payload(
        {
            "kind": RuntimePayloadKind.COMPUTE_REQUEST.value,
            "request_id": "request-1",
            "namespace": "tenant-a",
            "compute_kind": 14,
        }
    )

    assert request_hub.version() == previous_version + 1
    assert request_hub.payloads_since(previous_version) == [ComputeRequestWake("request-1", "tenant-a", 14)]


@pytest.mark.asyncio
async def test_compute_response_notification_wakes_queued_namespace_work() -> None:
    await request_hub.clear()
    previous_version = request_hub.version()

    await runtime_notifications.handle_runtime_payload(
        {
            "kind": RuntimePayloadKind.COMPUTE_RESPONSE.value,
            "request_id": "request-1",
            "namespace": "tenant-a",
        }
    )

    assert request_hub.version() == previous_version + 1
    assert request_hub.payloads_since(previous_version) == [ComputeRequestWake(None, "tenant-a", None)]

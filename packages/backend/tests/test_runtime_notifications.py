import os

import pytest


@pytest.mark.asyncio
async def test_lock_notification_fans_out_to_watchers_from_another_api_process(monkeypatch) -> None:
    from backend_core import runtime_notifications

    received = []

    async def notify_watchers(namespace, resource_type, resource_id, payload) -> None:
        received.append((namespace, resource_type, resource_id, payload))

    monkeypatch.setattr(runtime_notifications.lock_watchers, 'notify_watchers', notify_watchers)
    status = {'type': 'status', 'resource_type': 'analysis', 'resource_id': 'analysis-1', 'lock': None}

    await runtime_notifications.handle_runtime_payload(
        {
            'kind': 'lock',
            'namespace': 'default',
            'resource_type': 'analysis',
            'resource_id': 'analysis-1',
            'status': status,
            'source_pid': os.getpid() + 1,
        }
    )

    assert received == [('default', 'analysis', 'analysis-1', status)]


@pytest.mark.asyncio
async def test_lock_notification_does_not_echo_to_the_publishing_api_process(monkeypatch) -> None:
    from backend_core import runtime_notifications

    async def fail_notify(*args) -> None:
        raise AssertionError('same-process lock notification should be handled locally')

    monkeypatch.setattr(runtime_notifications.lock_watchers, 'notify_watchers', fail_notify)

    await runtime_notifications.handle_runtime_payload(
        {
            'kind': 'lock',
            'namespace': 'default',
            'resource_type': 'analysis',
            'resource_id': 'analysis-1',
            'status': {'lock': None},
            'source_pid': os.getpid(),
        }
    )


def test_notify_api_lock_includes_process_identity(monkeypatch) -> None:
    from backend_core import runtime_ipc

    sent = []
    monkeypatch.setattr(
        runtime_ipc,
        '_send_api_message',
        lambda payload, *, listener: sent.append((payload, listener)),
    )
    status: dict[str, object] = {'type': 'status', 'lock': None}

    runtime_ipc.notify_api_lock('default', 'analysis', 'analysis-1', status)

    assert sent == [
        (
            {
                'kind': 'lock',
                'namespace': 'default',
                'resource_type': 'analysis',
                'resource_id': 'analysis-1',
                'status': status,
                'source_pid': os.getpid(),
            },
            runtime_ipc.RuntimeListenerKind.API,
        )
    ]

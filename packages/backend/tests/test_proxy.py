from __future__ import annotations

from typing import Any, cast

from fastapi import Request
from starlette.types import Scope

from backend_core.proxy import client_ip, request_scheme


def _request(scope_overrides: dict[str, Any] | None = None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
    }
    if scope_overrides:
        scope.update(scope_overrides)
    return Request(cast(Scope, scope))


def test_client_ip_uses_socket_client_without_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings.trusted_proxy_hops", 0)
    request = _request(
        {
            "headers": [(b"x-forwarded-for", b"198.51.100.1, 203.0.113.5")],
            "client": ("10.0.0.4", 1234),
        }
    )

    assert client_ip(request) == "10.0.0.4"


def test_client_ip_uses_forwarded_chain_with_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings.trusted_proxy_hops", 1)
    request = _request(
        {
            "headers": [(b"x-forwarded-for", b"198.51.100.1, 203.0.113.5")],
            "client": ("10.0.0.4", 1234),
        }
    )

    assert client_ip(request) == "198.51.100.1"


def test_client_ip_falls_back_to_first_forwarded_value_when_chain_short(
    monkeypatch,
) -> None:
    monkeypatch.setattr("core.config.settings.trusted_proxy_hops", 2)
    request = _request({"headers": [(b"x-forwarded-for", b"198.51.100.1")]})

    assert client_ip(request) == "198.51.100.1"


def test_request_scheme_uses_socket_scheme_without_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings.trusted_proxy_hops", 0)
    request = _request({"headers": [(b"x-forwarded-proto", b"https")], "scheme": "http"})

    assert request_scheme(request) == "http"


def test_request_scheme_uses_forwarded_proto_with_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings.trusted_proxy_hops", 1)
    request = _request({"headers": [(b"x-forwarded-proto", b"https,http")], "scheme": "http"})

    assert request_scheme(request) == "https"

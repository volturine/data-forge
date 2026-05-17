from core.config import settings
from fastapi import Request


def request_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded and settings.trusted_proxy_hops > 0:
        return forwarded.split(",")[0].strip().lower()
    return request.url.scheme.lower()


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and settings.trusted_proxy_hops > 0:
        parts = [item.strip() for item in forwarded.split(",") if item.strip()]
        if len(parts) > settings.trusted_proxy_hops:
            return parts[-(settings.trusted_proxy_hops + 1)][:128]
        return parts[0][:128]
    if request.client:
        return str(request.client.host)
    return None

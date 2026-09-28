from __future__ import annotations

from dataclasses import dataclass

from runtime.live_hubs import VersionHub


@dataclass(frozen=True, slots=True)
class ComputeRequestWake:
    request_id: str | None
    namespace: str
    kind: int | None


request_hub: VersionHub[ComputeRequestWake] = VersionHub()

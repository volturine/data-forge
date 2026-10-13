from __future__ import annotations

from dataclasses import dataclass

from runtime.domain.compute import schemas


@dataclass(slots=True)
class RuntimeBuild:
    build_id: str
    analysis_id: str
    analysis_name: str
    namespace: str
    starter: schemas.BuildStarter
    total_steps: int = 0
    current_kind: str | None = None
    current_datasource_id: str | None = None
    current_tab_id: str | None = None
    current_tab_name: str | None = None
    current_output_id: str | None = None
    current_output_name: str | None = None
    current_compute_worker_run_id: str | None = None
    resource_config: schemas.BuildResourceConfigSummary | None = None

    @property
    def resource_config_json(self) -> dict[str, object] | None:
        if self.resource_config is None:
            return None
        return self.resource_config.model_dump(mode="json")

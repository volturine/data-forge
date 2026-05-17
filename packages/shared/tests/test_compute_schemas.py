from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from contracts.compute.schemas import (
    ActiveBuildStatus,
    BuildCancelledEvent,
    BuildCompleteEvent,
    BuildEventAdapter,
    BuildEventType,
    BuildFailedEvent,
    BuildStepState,
    BuildTabResult,
    BuildTabStatus,
    ComputeRunStatus,
    StepPreviewRequest,
)


def test_build_tab_result_status_is_enum_backed() -> None:
    schema = BuildTabResult.model_json_schema()
    status_schema = schema.get('properties', {}).get('status', {})
    enum_values = status_schema.get('enum')
    if enum_values is None:
        ref = status_schema.get('$ref')
        if isinstance(ref, str):
            enum_values = schema.get('$defs', {}).get(ref.split('/')[-1], {}).get('enum')

    assert enum_values == ['success', 'failed']

    result = BuildTabResult(tab_id='tab-1', tab_name='Tab 1', status=BuildTabStatus.SUCCESS)
    assert result.status is BuildTabStatus.SUCCESS
    assert result.model_dump()['status'] == 'success'


def test_compute_run_status_enum_values_are_explicit() -> None:
    assert ComputeRunStatus.SUCCESS.value == 'success'
    assert ComputeRunStatus.FAILED.value == 'failed'


def test_build_event_type_enum_values_are_explicit() -> None:
    assert BuildEventType.PLAN.value == 'plan'
    assert BuildEventType.STEP_START.value == 'step_start'
    assert BuildEventType.STEP_COMPLETE.value == 'step_complete'
    assert BuildEventType.STEP_FAILED.value == 'step_failed'
    assert BuildEventType.PROGRESS.value == 'progress'
    assert BuildEventType.RESOURCES.value == 'resources'
    assert BuildEventType.LOG.value == 'log'
    assert BuildEventType.COMPLETE.value == 'complete'
    assert BuildEventType.FAILED.value == 'failed'
    assert BuildEventType.CANCELLED.value == 'cancelled'


def test_build_event_type_owns_live_build_mappings() -> None:
    assert BuildEventType.STEP_START.step_state == BuildStepState.RUNNING
    assert BuildEventType.STEP_COMPLETE.step_state == BuildStepState.COMPLETED
    assert BuildEventType.STEP_FAILED.step_state == BuildStepState.FAILED
    assert BuildEventType.COMPLETE.terminal_build_status == ActiveBuildStatus.COMPLETED
    assert BuildEventType.CANCELLED.terminal_build_status == ActiveBuildStatus.CANCELLED
    assert BuildEventType.CANCELLED.terminal_error_message == 'Build cancelled'
    assert ActiveBuildStatus.RUNNING.is_terminal is False
    assert ActiveBuildStatus.FAILED.is_terminal is True


def test_build_event_union_validates_terminal_events() -> None:
    now = datetime.now(UTC)
    results = [BuildTabResult(tab_id='tab-1', tab_name='Tab 1', status=BuildTabStatus.SUCCESS)]

    complete = BuildCompleteEvent(
        build_id='build-1', analysis_id='analysis-1', emitted_at=now, elapsed_ms=100, total_steps=2, tabs_built=1, results=results, duration_ms=100
    )
    failed = BuildFailedEvent(
        build_id='build-1',
        analysis_id='analysis-1',
        emitted_at=now,
        progress=0.5,
        elapsed_ms=100,
        total_steps=2,
        tabs_built=1,
        results=results,
        duration_ms=100,
        error='boom',
    )
    cancelled = BuildCancelledEvent(
        build_id='build-1',
        analysis_id='analysis-1',
        emitted_at=now,
        progress=0.5,
        elapsed_ms=100,
        total_steps=2,
        tabs_built=1,
        results=results,
        duration_ms=100,
        cancelled_at=now,
        cancelled_by='user-1',
    )

    assert BuildEventAdapter.validate_python(complete.model_dump(mode='json')).type == BuildEventType.COMPLETE
    assert BuildEventAdapter.validate_python(failed.model_dump(mode='json')).type == BuildEventType.FAILED
    assert BuildEventAdapter.validate_python(cancelled.model_dump(mode='json')).type == BuildEventType.CANCELLED


def _pipeline_payload() -> dict:
    return {
        'analysis_id': 'analysis-1',
        'tabs': [
            {
                'id': 'tab-1',
                'datasource': {'id': 'datasource-1', 'analysis_tab_id': 'tab-1', 'config': {'branch': 'main'}},
                'output': {'result_id': 'result-1', 'filename': 'result', 'format': 'csv'},
                'steps': [],
            }
        ],
    }


def test_step_preview_request_bounds_pagination() -> None:
    payload = {'target_step_id': 'source', 'analysis_pipeline': _pipeline_payload()}

    request = StepPreviewRequest.model_validate(payload)

    assert request.row_limit == 1000
    assert request.page == 1


@pytest.mark.parametrize(('field', 'value'), [('row_limit', 0), ('row_limit', 5001), ('page', 0)])
def test_step_preview_request_rejects_unbounded_pagination(field: str, value: int) -> None:
    payload = {'target_step_id': 'source', 'analysis_pipeline': _pipeline_payload(), field: value}

    with pytest.raises(ValidationError):
        StepPreviewRequest.model_validate(payload)


def test_analysis_pipeline_payload_rejects_unknown_step_type() -> None:
    payload: dict[str, Any] = {'target_step_id': 'source', 'analysis_pipeline': _pipeline_payload()}
    payload['analysis_pipeline']['tabs'][0]['steps'] = [{'id': 'step-1', 'type': 'typo', 'config': {}, 'depends_on': []}]

    with pytest.raises(ValidationError, match='unknown type'):
        StepPreviewRequest.model_validate(payload)


def test_analysis_pipeline_payload_rejects_unknown_step_fields() -> None:
    payload: dict[str, Any] = {'target_step_id': 'source', 'analysis_pipeline': _pipeline_payload()}
    payload['analysis_pipeline']['tabs'][0]['steps'] = [{'id': 'step-1', 'type': 'filter', 'config': {}, 'depends_on': [], 'surprise': True}]

    with pytest.raises(ValidationError, match='unknown field'):
        StepPreviewRequest.model_validate(payload)


def test_build_event_union_rejects_missing_terminal_progress() -> None:
    with pytest.raises(ValidationError):
        BuildEventAdapter.validate_python(
            {
                'type': 'failed',
                'build_id': 'build-1',
                'analysis_id': 'analysis-1',
                'emitted_at': datetime.now(UTC).isoformat(),
                'elapsed_ms': 100,
                'total_steps': 2,
                'tabs_built': 1,
                'results': [{'tab_id': 'tab-1', 'tab_name': 'Tab 1', 'status': 'failed'}],
                'duration_ms': 100,
            }
        )

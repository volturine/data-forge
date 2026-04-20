from modules.compute.schemas import BuildEventType, BuildTabResult, BuildTabStatus, ComputeRunStatus


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

import json
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, col

from core.exceptions import (
    AnalysisCycleError,
    AnalysisNotFoundError,
    AnalysisValidationError,
    DataSourceNotFoundError,
)
from modules.ai.service import AIError, get_ai_client
from modules.analysis.models import Analysis, AnalysisDataSource, AnalysisStatus
from modules.analysis.pipeline_types import PipelineDefinition, PipelineStep, PipelineTab, TabDatasource, TabOutput
from modules.analysis.schemas import (
    AnalysisCreateSchema,
    AnalysisGalleryItemSchema,
    AnalysisGenerationDatasourceSchema,
    AnalysisResponseSchema,
    AnalysisUpdateSchema,
    DuplicateAnalysisSchema,
    GenerateAnalysisSchema,
    ImportAnalysisSchema,
    TabSchema,
)
from modules.analysis.step_schemas import validate_step
from modules.analysis.templates import AnalysisTemplate, get_template, list_templates
from modules.analysis_versions import service as version_service
from modules.datasource.models import DataSource
from modules.settings.service import (
    get_resolved_huggingface_settings,
    get_resolved_ollama_settings,
    get_resolved_openai_settings,
    get_resolved_openrouter_key,
)


def _to_response(analysis: Analysis) -> AnalysisResponseSchema:
    return AnalysisResponseSchema.model_validate(analysis)


def _slugify(value: str) -> str:
    normalized = re.sub(r'[^a-zA-Z0-9]+', '_', value.strip().lower()).strip('_')
    return normalized or 'analysis'


def _default_output_name(analysis_name: str, tab_name: str, index: int) -> str:
    return _slugify(f'{analysis_name}_{tab_name or f"tab_{index + 1}"}')


def _build_output_config(analysis_name: str, tab_name: str, branch: str, index: int) -> dict[str, Any]:
    output_name = _default_output_name(analysis_name, tab_name, index)
    return {
        'result_id': str(uuid.uuid4()),
        'format': 'parquet',
        'filename': output_name,
        'build_mode': 'full',
        'iceberg': {
            'namespace': 'outputs',
            'table_name': output_name,
            'branch': branch,
        },
    }


def _clone_step_config(config: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(config)


def _build_template_steps(template: AnalysisTemplate) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for raw in template.steps:
        steps.append(
            {
                'id': str(uuid.uuid4()),
                'type': str(raw['type']),
                'config': _clone_step_config(raw.get('config', {})),
                'depends_on': [],
                'is_applied': True,
            },
        )
    return steps


def _datasource_config_from_request(item: AnalysisGenerationDatasourceSchema) -> dict[str, Any]:
    config: dict[str, Any] = {'branch': item.branch}
    if item.snapshot_id is not None:
        config['snapshot_id'] = item.snapshot_id
    if item.snapshot_timestamp_ms is not None:
        config['snapshot_timestamp_ms'] = item.snapshot_timestamp_ms
    return config


def _build_tabs_from_template(
    analysis_name: str,
    datasources: list[AnalysisGenerationDatasourceSchema],
    template: AnalysisTemplate,
) -> list[dict[str, Any]]:
    if not datasources:
        raise ValueError('At least one datasource is required')

    tabs: list[dict[str, Any]] = []
    first_output_id: str | None = None
    first_tab_id: str | None = None
    for index, datasource in enumerate(datasources):
        tab_id = str(uuid.uuid4())
        branch = datasource.branch.strip()
        tab_name = f'Source {index + 1}'
        steps = _build_template_steps(template)
        if template.id == 'join_and_enrich' and index > 0:
            steps = []
        if template.id == 'join_and_enrich' and index == 0 and len(datasources) > 1:
            for step in steps:
                if step['type'] == 'join':
                    step['config']['right_source'] = datasources[1].id
        output = _build_output_config(analysis_name, tab_name, branch, index)
        tabs.append(
            {
                'id': tab_id,
                'name': tab_name,
                'parent_id': None,
                'datasource': {
                    'id': datasource.id,
                    'analysis_tab_id': None,
                    'config': _datasource_config_from_request(datasource),
                },
                'output': output,
                'steps': steps,
            },
        )
        if first_output_id is None:
            first_output_id = output['result_id']
            first_tab_id = tab_id

    if template.id == 'join_and_enrich' and len(tabs) > 1 and first_output_id and first_tab_id:
        for index, tab in enumerate(tabs[1:], start=1):
            tab['datasource'] = {
                'id': first_output_id,
                'analysis_tab_id': first_tab_id,
                'config': dict(tab['datasource']['config']),
            }
            tab['steps'] = []
            tab['parent_id'] = first_tab_id
            tab['name'] = f'Joined Output {index + 1}'
    return tabs


def _extract_json_object(content: str) -> dict[str, Any]:
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', content, re.DOTALL)
    candidate = fenced.group(1) if fenced else content.strip()
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(candidate)
    except json.JSONDecodeError as exc:
        brace_index = candidate.find('{')
        if brace_index < 0:
            raise ValueError('AI response did not contain JSON') from exc
        obj, _ = decoder.raw_decode(candidate[brace_index:])
    if not isinstance(obj, dict):
        raise ValueError('AI response must be a JSON object')
    return obj


def _rewrite_import_payload(
    pipeline: dict[str, Any],
    datasource_remap: dict[str, str],
) -> dict[str, Any]:
    rewritten = deepcopy(pipeline)
    tabs = rewritten.get('tabs')
    if not isinstance(tabs, list):
        raise ValueError("Imported pipeline must contain a 'tabs' array")

    output_id_map: dict[str, str] = {}
    tab_id_map: dict[str, str] = {}
    step_id_map: dict[str, str] = {}

    for tab in tabs:
        if not isinstance(tab, dict):
            raise ValueError('Imported pipeline tabs must be objects')
        old_tab_id = str(tab.get('id', ''))
        new_tab_id = str(uuid.uuid4())
        tab_id_map[old_tab_id] = new_tab_id
        tab['id'] = new_tab_id
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Imported pipeline tabs must include output')
        old_output_id = str(output.get('result_id', ''))
        new_output_id = str(uuid.uuid4())
        output_id_map[old_output_id] = new_output_id
        output['result_id'] = new_output_id
        steps = tab.get('steps')
        if not isinstance(steps, list):
            raise ValueError('Imported pipeline steps must be a list')
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError('Imported pipeline steps must be objects')
            old_step_id = str(step.get('id', ''))
            new_step_id = str(uuid.uuid4())
            step_id_map[old_step_id] = new_step_id
            step['id'] = new_step_id
            step['is_applied'] = True

    for tab in tabs:
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            raise ValueError('Imported pipeline tabs must include datasource')
        original_id = str(datasource.get('id', ''))
        analysis_tab_id = datasource.get('analysis_tab_id')
        if analysis_tab_id is not None:
            upstream_tab_id = str(analysis_tab_id)
            if upstream_tab_id not in tab_id_map:
                raise ValueError(f"Imported tab references missing upstream tab '{upstream_tab_id}'")
            datasource['analysis_tab_id'] = tab_id_map[upstream_tab_id]
            if original_id not in output_id_map:
                raise ValueError(f"Imported tab references missing upstream output '{original_id}'")
            datasource['id'] = output_id_map[original_id]
        elif original_id in datasource_remap:
            datasource['id'] = datasource_remap[original_id]
        steps = tab.get('steps', [])
        for step in steps:
            config = step.get('config')
            if isinstance(config, dict):
                right_source = config.get('right_source')
                if isinstance(right_source, str):
                    if right_source in output_id_map:
                        config['right_source'] = output_id_map[right_source]
                    elif right_source in tab_id_map:
                        config['right_source'] = tab_id_map[right_source]
                    elif right_source in datasource_remap:
                        config['right_source'] = datasource_remap[right_source]
                sources = config.get('sources')
                if isinstance(sources, list):
                    rewritten_sources: list[Any] = []
                    for source in sources:
                        if isinstance(source, str):
                            rewritten_sources.append(
                                output_id_map.get(source) or tab_id_map.get(source) or datasource_remap.get(source) or source
                            )
                        else:
                            rewritten_sources.append(source)
                    config['sources'] = rewritten_sources
            depends_on = step.get('depends_on')
            if isinstance(depends_on, list):
                step['depends_on'] = [step_id_map.get(str(dep_id), str(dep_id)) for dep_id in depends_on]

    return rewritten


def _collect_missing_import_datasources(session: Session, pipeline: dict[str, Any]) -> list[str]:  # type: ignore[type-arg]
    missing: set[str] = set()
    tabs = pipeline.get('tabs')
    if not isinstance(tabs, list):
        return []
    tab_ids = {str(tab.get('id', '')) for tab in tabs if isinstance(tab, dict)}
    output_ids = {
        str(tab.get('output', {}).get('result_id', '')) for tab in tabs if isinstance(tab, dict) and isinstance(tab.get('output'), dict)
    }
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            continue
        datasource_id = str(datasource.get('id', ''))
        if datasource.get('analysis_tab_id') is None and datasource_id not in output_ids and not session.get(DataSource, datasource_id):
            missing.add(datasource_id)
        for step in tab.get('steps', []):
            if not isinstance(step, dict):
                continue
            config = step.get('config')
            if not isinstance(config, dict):
                continue
            refs: list[str] = []
            right_source = config.get('right_source')
            if isinstance(right_source, str):
                refs.append(right_source)
            sources = config.get('sources')
            if isinstance(sources, list):
                refs.extend(str(source) for source in sources if isinstance(source, str))
            for ref in refs:
                if ref in tab_ids or ref in output_ids:
                    continue
                if not session.get(DataSource, ref):
                    missing.add(ref)
    return sorted(missing)


def _resolved_generation_provider(provider: str | None = None) -> tuple[str, str, dict[str, str]]:
    requested = provider.strip().lower() if provider else ''
    if requested == 'openrouter':
        api_key = get_resolved_openrouter_key()
        if not api_key:
            raise ValueError('OpenRouter is not configured')
        return 'openrouter', '', {'api_key': api_key}
    if requested == 'openai':
        resolved = get_resolved_openai_settings()
        if not resolved['api_key']:
            raise ValueError('OpenAI is not configured')
        return (
            'openai',
            str(resolved['default_model']),
            {
                'api_key': str(resolved['api_key']),
                'endpoint_url': str(resolved['endpoint_url']),
                'organization_id': str(resolved['organization_id']),
            },
        )
    if requested == 'ollama':
        resolved = get_resolved_ollama_settings()
        return 'ollama', str(resolved['default_model']), {'endpoint_url': str(resolved['endpoint_url'])}
    if requested == 'huggingface':
        resolved = get_resolved_huggingface_settings()
        if not resolved['api_token']:
            raise ValueError('Hugging Face is not configured')
        return 'huggingface', str(resolved['default_model']), {'api_key': str(resolved['api_token'])}

    openrouter_key = get_resolved_openrouter_key()
    if openrouter_key:
        return 'openrouter', '', {'api_key': openrouter_key}
    openai = get_resolved_openai_settings()
    if openai['api_key']:
        return (
            'openai',
            str(openai['default_model']),
            {
                'api_key': str(openai['api_key']),
                'endpoint_url': str(openai['endpoint_url']),
                'organization_id': str(openai['organization_id']),
            },
        )
    ollama = get_resolved_ollama_settings()
    if ollama['endpoint_url']:
        return 'ollama', str(ollama['default_model']), {'endpoint_url': str(ollama['endpoint_url'])}
    huggingface = get_resolved_huggingface_settings()
    if huggingface['api_token']:
        return 'huggingface', str(huggingface['default_model']), {'api_key': str(huggingface['api_token'])}
    raise ValueError('No AI provider is configured')


def validate_stored_pipeline_definition(
    session: Session,  # type: ignore[type-arg]
    pipeline_definition: dict[str, Any],
    analysis_id: str,
) -> None:
    if not isinstance(pipeline_definition, dict):
        raise AnalysisValidationError('Analysis pipeline_definition must be a dict', details={'analysis_id': analysis_id})

    tabs = pipeline_definition.get('tabs')
    if not isinstance(tabs, list) or not tabs:
        raise AnalysisValidationError('Analysis requires at least one tab', details={'analysis_id': analysis_id})

    try:
        payload = AnalysisUpdateSchema(tabs=tabs)
    except ValidationError as exc:
        raise AnalysisValidationError(str(exc), details={'analysis_id': analysis_id}) from exc
    _validate_analysis_payload(session, payload, analysis_id)


def _validate_analysis_payload(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema | AnalysisUpdateSchema,
    analysis_id: str | None = None,
) -> tuple[list[PipelineTab], list[str]]:
    if not data.tabs:
        raise ValueError('Analysis requires at least one tab')
    tabs_payload = [PipelineTab.from_dict(tab.model_dump()) for tab in data.tabs]
    for tab in tabs_payload:
        if not tab.output.result_id:
            raise ValueError('Analysis tab missing output.result_id')
        if not tab.output.filename:
            raise ValueError('Analysis tab missing output.filename')
        if not tab.output.format:
            raise ValueError('Analysis tab missing output.format')

    tab_output_map: dict[str, str] = {}
    for tab in tabs_payload:
        if tab.id and tab.output.result_id:
            tab_output_map[tab.id] = tab.output.result_id

    datasource_ids: list[str] = []
    for tab in tabs_payload:
        ds = tab.datasource
        branch = ds.config.get('branch')
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError('Analysis tab datasource.config.branch is required')
        ds.config['branch'] = branch.strip()

        if not ds.id:
            raise ValueError('Analysis tab missing datasource.id')

        if ds.analysis_tab_id is not None:
            expected = tab_output_map.get(str(ds.analysis_tab_id))
            if expected != ds.id:
                raise ValueError(f"Datasource id '{ds.id}' does not match output.result_id of tab '{ds.analysis_tab_id}'")
            continue
        datasource_row = session.get(DataSource, ds.id)
        if datasource_row:
            datasource_ids.append(ds.id)
            if datasource_row.source_type == 'analysis' and analysis_id:
                source_id = _get_analysis_source_id(datasource_row)
                _ensure_no_cycle(session, analysis_id, source_id)
            continue
        raise DataSourceNotFoundError(ds.id)

    tab_ids = {tab.id for tab in tabs_payload if tab.id}

    referenced_source_ids: set[str] = set()
    for tab in tabs_payload:
        for step in tab.steps:
            cfg = step.config
            rs = cfg.get('right_source')
            if isinstance(rs, str) and rs:
                referenced_source_ids.add(rs)
            sources = cfg.get('sources')
            if isinstance(sources, list):
                for src in sources:
                    if isinstance(src, str) and src:
                        referenced_source_ids.add(src)

    unknown = referenced_source_ids - tab_ids
    for src_id in unknown:
        if not session.get(DataSource, src_id):
            raise ValueError(f"Step references unknown source '{src_id}'")
        datasource_ids.append(src_id)

    for tab in tabs_payload:
        step_ids: set[str] = set()
        for step in tab.steps:
            validate_step(step.type, step.config)
            if step.id:
                step_ids.add(step.id)
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(f"Step depends on unknown step '{dep_id}'")

    return tabs_payload, datasource_ids


def validate_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> dict[str, Any]:
    """Validate analysis payload without persisting."""
    tabs_payload, _ = _validate_analysis_payload(session, data)
    return {'valid': True, 'payload': {'tabs': [t.to_dict() for t in tabs_payload]}}


def create_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
    owner_id: str | None = None,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    tabs_payload, datasource_ids = _validate_analysis_payload(session, data, analysis_id)

    pipeline_definition = PipelineDefinition(tabs=tabs_payload).to_dict()

    now = datetime.now(UTC).replace(tzinfo=None)
    analysis = Analysis(
        id=analysis_id,
        name=data.name,
        description=data.description,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=now,
        updated_at=now,
        owner_id=owner_id,
    )

    session.add(analysis)

    seen: set[str] = set()
    for datasource_id in datasource_ids:
        if datasource_id in seen:
            continue
        seen.add(datasource_id)
        link = AnalysisDataSource(
            analysis_id=analysis_id,
            datasource_id=datasource_id,
        )
        session.add(link)

    version_service.create_version(session, analysis, commit=False)
    session.commit()

    session.refresh(analysis)
    return _to_response(analysis)


def get_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    return _to_response(analysis)


def list_analyses(
    session: Session,  # type: ignore[type-arg]
) -> list[AnalysisGalleryItemSchema]:
    stmt = select(Analysis).options(
        defer(Analysis.pipeline_definition),  # type: ignore[arg-type]
        defer(Analysis.description),  # type: ignore[arg-type]
        defer(Analysis.status),  # type: ignore[arg-type]
        defer(Analysis.result_path),  # type: ignore[arg-type]
        defer(Analysis.owner_id),  # type: ignore[arg-type]
    )
    return [AnalysisGalleryItemSchema.model_validate(a) for a in session.execute(stmt).scalars()]


def list_analysis_templates() -> list[dict[str, Any]]:
    return list_templates()


def get_analysis_template(template_id: str) -> dict[str, Any]:
    return get_template(template_id).to_detail()


def duplicate_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    data: DuplicateAnalysisSchema,
    owner_id: str | None = None,
) -> AnalysisResponseSchema:
    original = session.get(Analysis, analysis_id)
    if not original:
        raise AnalysisNotFoundError(analysis_id)

    pipeline = deepcopy(original.pipeline_definition)
    tabs = pipeline.get('tabs')
    if not isinstance(tabs, list):
        raise ValueError('Source analysis pipeline is invalid')

    output_id_map: dict[str, str] = {}
    tab_id_map: dict[str, str] = {}
    step_id_map: dict[str, str] = {}

    for index, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            raise ValueError('Source analysis tabs are invalid')
        old_tab_id = str(tab.get('id', ''))
        new_tab_id = str(uuid.uuid4())
        tab_id_map[old_tab_id] = new_tab_id
        tab['id'] = new_tab_id

        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Source analysis tab output is invalid')
        old_output_id = str(output.get('result_id', ''))
        new_output_id = str(uuid.uuid4())
        output_id_map[old_output_id] = new_output_id
        output['result_id'] = new_output_id
        branch = str(((output.get('iceberg') or {}) if isinstance(output.get('iceberg'), dict) else {}).get('branch') or 'master')
        output_name = _default_output_name(data.name, str(tab.get('name') or f'tab_{index + 1}'), index)
        output['filename'] = output_name
        iceberg = output.get('iceberg')
        if isinstance(iceberg, dict):
            iceberg['table_name'] = output_name
            iceberg['branch'] = str(iceberg.get('branch') or branch)

        steps = tab.get('steps', [])
        if not isinstance(steps, list):
            raise ValueError('Source analysis tab steps are invalid')
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError('Source analysis steps are invalid')
            old_step_id = str(step.get('id', ''))
            new_step_id = str(uuid.uuid4())
            step_id_map[old_step_id] = new_step_id
            step['id'] = new_step_id

    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        datasource = tab.get('datasource')
        if isinstance(datasource, dict):
            upstream_tab_id = datasource.get('analysis_tab_id')
            if upstream_tab_id is not None:
                mapped_tab_id = tab_id_map.get(str(upstream_tab_id))
                if not mapped_tab_id:
                    raise ValueError(f"Duplicate source references missing tab '{upstream_tab_id}'")
                datasource['analysis_tab_id'] = mapped_tab_id
                source_id = str(datasource.get('id', ''))
                if source_id not in output_id_map:
                    raise ValueError(f"Duplicate source references missing output '{source_id}'")
                datasource['id'] = output_id_map[source_id]
        for step in tab.get('steps', []):
            if not isinstance(step, dict):
                continue
            depends_on = step.get('depends_on')
            if isinstance(depends_on, list):
                step['depends_on'] = [step_id_map.get(str(dep_id), str(dep_id)) for dep_id in depends_on]
            config = step.get('config')
            if isinstance(config, dict):
                right_source = config.get('right_source')
                if isinstance(right_source, str):
                    config['right_source'] = output_id_map.get(right_source) or tab_id_map.get(right_source) or right_source
                sources = config.get('sources')
                if isinstance(sources, list):
                    config['sources'] = [
                        output_id_map.get(source) or tab_id_map.get(source) or source if isinstance(source, str) else source
                        for source in sources
                    ]

    payload = AnalysisCreateSchema(
        name=data.name,
        description=data.description if data.description is not None else original.description,
        tabs=tabs,
    )
    return create_analysis(session, payload, owner_id=owner_id)


def import_analysis(
    session: Session,  # type: ignore[type-arg]
    data: ImportAnalysisSchema,
    owner_id: str | None = None,
) -> AnalysisResponseSchema:
    rewritten = _rewrite_import_payload(data.pipeline, data.datasource_remap)
    missing = _collect_missing_import_datasources(session, rewritten)
    if missing:
        raise AnalysisValidationError(
            'Imported pipeline references datasources that do not exist',
            details={'missing_datasource_ids': missing},
        )
    tabs = rewritten.get('tabs')
    if not isinstance(tabs, list):
        raise ValueError("Imported pipeline must contain a 'tabs' array")
    payload = AnalysisCreateSchema(
        name=data.name,
        description=data.description,
        tabs=tabs,
    )
    return create_analysis(session, payload, owner_id=owner_id)


def generate_analysis_pipeline(
    session: Session,  # type: ignore[type-arg]
    data: GenerateAnalysisSchema,
) -> dict[str, Any]:
    if not data.datasources:
        raise ValueError('At least one datasource is required for generation')

    selected_datasources: list[DataSource] = []
    datasource_schemas: list[dict[str, Any]] = []
    for item in data.datasources:
        datasource = session.get(DataSource, item.id)
        if not datasource:
            raise DataSourceNotFoundError(item.id)
        selected_datasources.append(datasource)
        schema_cache = datasource.schema_cache if isinstance(datasource.schema_cache, dict) else {}
        datasource_schemas.append(
            {
                'id': datasource.id,
                'name': datasource.name,
                'source_type': datasource.source_type,
                'branch': item.branch,
                'columns': schema_cache.get('columns', []),
            },
        )

    provider_name, default_model, client_kwargs = _resolved_generation_provider(data.provider)
    model_name = data.model.strip() if data.model else default_model
    if not model_name:
        raise ValueError('No model configured for the selected AI provider')

    operation_summaries = []
    from modules.analysis.step_schemas import get_step_catalog

    operation_catalog = get_step_catalog()
    for operation in operation_catalog:
        operation_summaries.append(
            {
                'type': operation['type'],
                'description': operation['description'],
                'config_schema': operation['config_schema'],
            },
        )

    prompt = '\n'.join(
        [
            'Generate a JSON object for a new analysis pipeline.',
            'Return JSON only. No markdown fences.',
            'Schema:',
            '{',
            '  "explanation": "short explanation",',
            '  "tabs": [',
            '    {',
            '      "name": "tab name",',
            '      "datasource_id": "one of the datasource ids below",',
            '      "steps": [',
            '        {"type": "filter", "config": {...}},',
            '        {"type": "select", "config": {...}}',
            '      ]',
            '    }',
            '  ]',
            '}',
            '',
            'Rules:',
            '- Use only datasource ids listed below.',
            '- Use only operation types listed below.',
            '- Return at most one tab per datasource.',
            '- Prefer concise, editable skeletons over complex configs.',
            (
                '- If multiple datasources are available and a join makes sense, '
                'use the first datasource as the primary tab and reference the '
                'second datasource id in join.right_source.'
            ),
            '',
            f'Analysis name: {data.name}',
            f'User request: {data.description}',
            'Datasources:',
            json.dumps(datasource_schemas, indent=2),
            'Operations:',
            json.dumps(operation_summaries, indent=2),
        ],
    )

    client = get_ai_client(provider_name, **client_kwargs)
    try:
        raw_response = client.generate(prompt, model=model_name, options={'temperature': 0.2})
    except AIError as exc:
        raise ValueError(str(exc)) from exc

    generated = _extract_json_object(raw_response)
    raw_tabs = generated.get('tabs')
    if not isinstance(raw_tabs, list) or not raw_tabs:
        raise ValueError('AI response did not include any tabs')

    datasource_inputs = {item.id: item for item in data.datasources}
    tabs_payload: list[TabSchema] = []
    for index, raw_tab in enumerate(raw_tabs):
        if not isinstance(raw_tab, dict):
            raise ValueError('AI tab entries must be objects')
        datasource_id = str(raw_tab.get('datasource_id', '')).strip()
        if not datasource_id or datasource_id not in datasource_inputs:
            raise ValueError('AI response referenced an unknown datasource')
        selected = datasource_inputs[datasource_id]
        branch = selected.branch
        tab_name = str(raw_tab.get('name') or f'Source {index + 1}')
        steps = raw_tab.get('steps')
        if not isinstance(steps, list):
            raise ValueError('AI tab steps must be a list')
        built_steps: list[dict[str, Any]] = []
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                raise ValueError('AI steps must be objects')
            built_steps.append(
                {
                    'id': str(uuid.uuid4()),
                    'type': str(raw_step.get('type', '')),
                    'config': deepcopy(raw_step.get('config', {})) if isinstance(raw_step.get('config'), dict) else {},
                    'depends_on': [],
                    'is_applied': True,
                },
            )
        tabs_payload.append(
            TabSchema.model_validate(
                {
                    'id': str(uuid.uuid4()),
                    'name': tab_name,
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_id,
                        'analysis_tab_id': None,
                        'config': _datasource_config_from_request(selected),
                    },
                    'output': _build_output_config(data.name, tab_name, branch, index),
                    'steps': built_steps,
                },
            ),
        )

    payload = AnalysisCreateSchema(name=data.name, description=None, tabs=tabs_payload)
    validation = validate_analysis(session, payload)
    return {
        'pipeline': payload,
        'validation': validation,
        'explanation': str(generated.get('explanation') or raw_response).strip(),
        'provider': provider_name,
        'model': model_name,
    }


def update_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    data: AnalysisUpdateSchema,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    if data.name is not None:
        analysis.name = data.name

    if data.description is not None:
        analysis.description = data.description

    if data.tabs is not None:
        tabs_payload, datasource_ids = _validate_analysis_payload(session, data, analysis_id)
        analysis.pipeline_definition = PipelineDefinition(tabs=tabs_payload).to_dict()

        session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))
        for ds_id in set(datasource_ids):
            session.add(
                AnalysisDataSource(
                    analysis_id=analysis_id,
                    datasource_id=ds_id,
                ),
            )

    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.commit()
    session.refresh(analysis)
    return _to_response(analysis)


def delete_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> None:
    from modules.datasource.service import _delete_datasource_files

    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    created_datasources = (
        session.execute(
            select(DataSource).where(col(DataSource.created_by_analysis_id) == analysis_id),  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )

    for ds in created_datasources:
        if ds.is_hidden:
            _delete_datasource_files(ds)
            session.delete(ds)

    session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))  # type: ignore[arg-type]

    session.delete(analysis)
    session.commit()


def _get_analysis_source_id(datasource: DataSource) -> str:
    analysis_id = datasource.created_by_analysis_id
    if not analysis_id:
        raise ValueError(f'Analysis datasource {datasource.id} missing created_by_analysis_id')
    return str(analysis_id)


def _ensure_no_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> None:
    if analysis_id == source_analysis_id:
        raise AnalysisCycleError('Analysis cannot use itself as a datasource')
    if _detect_cycle(session, analysis_id, source_analysis_id):
        raise AnalysisCycleError('Analysis datasource introduces a cycle')


def _detect_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> bool:
    visited: set[str] = set()

    def visit(target_id: str) -> bool:
        if target_id == analysis_id:
            return True
        if target_id in visited:
            return False
        visited.add(target_id)
        links = (
            session.execute(
                select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == target_id),  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        datasources = [session.get(DataSource, link.datasource_id) for link in links]
        for datasource in datasources:
            if not datasource:
                continue
            if datasource.source_type != 'analysis':
                continue
            next_id = datasource.created_by_analysis_id
            if not next_id:
                continue
            if visit(str(next_id)):
                return True
        return False

    return visit(source_analysis_id)


def add_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_type: str,
    config: dict[str, object],
    position: int | None = None,
    depends_on: list[str] | None = None,
) -> PipelineStep:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    existing_step_ids = {s.id for s in tab.steps if s.id}
    for dep_id in depends_on or []:
        if dep_id not in existing_step_ids:
            raise ValueError(f"depends_on references unknown step '{dep_id}'")

    tab_ids = {t.id for t in pipeline.tabs if t.id}
    ds_ids = {t.datasource.id for t in pipeline.tabs if t.datasource.id}
    valid_source_ids = tab_ids | ds_ids

    def _is_valid_source(src_id: str) -> bool:
        if src_id in valid_source_ids:
            return True
        return session.get(DataSource, src_id) is not None

    right_source = config.get('right_source')
    if right_source and not _is_valid_source(str(right_source)):
        raise ValueError(f"Step references unknown source '{right_source}'")
    sources = config.get('sources')
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, str) and not _is_valid_source(src):
                raise ValueError(f"Step references unknown source '{src}'")

    step = PipelineStep(
        id=str(uuid.uuid4()),
        type=step_type,
        config=config,
        depends_on=depends_on or [],
        is_applied=True,
    )

    if position is None:
        tab.steps.append(step)
    else:
        pos = max(0, min(position, len(tab.steps)))
        tab.steps.insert(pos, step)

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return step


def get_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
) -> PipelineStep:
    """Get a step by ID from an analysis tab."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)
    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)
    step = next((s for s in tab.steps if s.id == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')
    return step


def update_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
    config: dict[str, object] | None = None,
    step_type: str | None = None,
) -> PipelineStep:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    step = next((s for s in tab.steps if s.id == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')

    if step_type is not None:
        step.type = step_type
    if config is not None:
        step.config = config

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return step


def remove_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
) -> None:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    idx = next((i for i, s in enumerate(tab.steps) if s.id == step_id), None)
    if idx is None:
        raise ValueError(f'Step {step_id} not found')

    tab.steps.pop(idx)

    for s in tab.steps:
        if step_id in s.depends_on:
            s.depends_on.remove(step_id)

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()


def derive_tab(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> PipelineTab:
    """Create a new tab whose datasource is the given tab's output result_id."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    pipeline = analysis.pipeline
    source = pipeline.find_tab(tab_id)

    if not source.output.result_id:
        raise ValueError(f'Tab {tab_id} has no output.result_id')

    tab_name = name or f'Derived {len(pipeline.tabs) + 1}'
    new_tab_id = f'tab-{uuid.uuid4()!s}'

    derived_step = PipelineStep(
        id=str(uuid.uuid4()),
        type='view',
        config={'rowLimit': 100},
        depends_on=[],
        is_applied=True,
    )

    new_tab = PipelineTab(
        id=new_tab_id,
        name=tab_name,
        parent_id=tab_id,
        datasource=TabDatasource(
            id=source.output.result_id,
            config={'branch': 'master'},
            analysis_tab_id=tab_id,
        ),
        output=TabOutput(
            result_id=str(uuid.uuid4()),
            format=source.output.format or 'parquet',
            filename=tab_name,
        ),
        steps=[derived_step],
    )

    pipeline.tabs.append(new_tab)
    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return new_tab


def _slugify_output_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return 'export'
    return re.sub(r'\s+', '_', stripped).lower()


def _next_duplicate_tab_name(tabs: list[PipelineTab], source_name: str) -> str:
    base = f'{source_name} Copy'
    existing = {tab.name for tab in tabs}
    if base not in existing:
        return base

    suffix = 2
    while True:
        candidate = f'{base} {suffix}'
        if candidate not in existing:
            return candidate
        suffix += 1


def duplicate_tab(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> PipelineTab:
    """Duplicate an existing tab in-place with fresh tab/step/output identities."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    pipeline = analysis.pipeline
    source = pipeline.find_tab(tab_id)

    new_tab_id = f'tab-{uuid.uuid4()!s}'
    next_name = name.strip() if isinstance(name, str) and name.strip() else _next_duplicate_tab_name(pipeline.tabs, source.name)

    step_id_map: dict[str, str] = {}
    duplicated_steps: list[PipelineStep] = []
    for step in source.steps:
        next_step_id = str(uuid.uuid4())
        step_id_map[step.id] = next_step_id
        duplicated_steps.append(
            PipelineStep(
                id=next_step_id,
                type=step.type,
                config=deepcopy(step.config),
                depends_on=[],
                is_applied=step.is_applied,
            )
        )

    for duplicated_step, source_step in zip(duplicated_steps, source.steps, strict=True):
        rewritten_deps: list[str] = []
        for dep_id in source_step.depends_on:
            mapped = step_id_map.get(dep_id)
            if not mapped:
                raise ValueError(f"Unable to rewrite dependency '{dep_id}' while duplicating tab '{tab_id}'")
            rewritten_deps.append(mapped)
        duplicated_step.depends_on = rewritten_deps

    duplicated_output = TabOutput.from_dict(source.output.to_dict())
    duplicated_output.result_id = str(uuid.uuid4())
    duplicated_output.filename = _slugify_output_name(next_name)

    iceberg = duplicated_output.extra.get('iceberg')
    if isinstance(iceberg, dict):
        duplicated_output.extra['iceberg'] = {
            **iceberg,
            'table_name': duplicated_output.filename,
        }

    duplicated_tab = PipelineTab(
        id=new_tab_id,
        name=next_name,
        parent_id=source.parent_id,
        datasource=TabDatasource(
            id=source.datasource.id,
            config=deepcopy(source.datasource.config),
            analysis_tab_id=source.datasource.analysis_tab_id,
        ),
        output=duplicated_output,
        steps=duplicated_steps,
    )

    source_idx = next((idx for idx, tab in enumerate(pipeline.tabs) if tab.id == tab_id), -1)
    if source_idx < 0:
        raise ValueError(f'Tab {tab_id} not found')

    pipeline.tabs.insert(source_idx + 1, duplicated_tab)
    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return duplicated_tab

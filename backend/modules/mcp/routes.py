"""MCP API routes — list tools, call tools, confirm pending actions."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from modules.mcp.executor import call_tool
from modules.mcp.pending import pending_store
from modules.mcp.registry import MUTATING_METHODS, build_tool_registry
from modules.mcp.validation import check_schema_supported, validate_args

router = APIRouter(prefix='/mcp', tags=['mcp'])

_registry_cache: list[dict] | None = None


def get_registry(app) -> list[dict]:  # type: ignore[no-untyped-def]
    """Return cached tool registry, building on first call."""
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = build_tool_registry(app)
    return _registry_cache


def reset_registry_cache() -> None:
    """Reset the registry cache — used in tests to ensure isolation."""
    global _registry_cache
    _registry_cache = None


class CallRequest(BaseModel):
    """Request body for MCP tool call."""

    tool_id: str
    args: dict[str, Any] = {}


class ConfirmRequest(BaseModel):
    """Request body for confirming a pending action."""

    token: str


class ValidateRequest(BaseModel):
    """Request body for validating tool args."""

    tool_id: str
    args: dict[str, Any] = {}


class PreflightRequest(BaseModel):
    """Request body for preflight check."""

    tool_id: str
    args: dict[str, Any] = {}


class CapabilitiesRequest(BaseModel):
    """Request body for schema capability check."""

    tool_ids: list[str] = []


@router.get('/tools')
def list_tools(request: Request) -> list[dict]:
    """List all available MCP tools derived from /api/v1 routes."""
    return get_registry(request.app)


@router.post('/validate')
def validate(request: Request, body: ValidateRequest) -> dict:
    """Validate tool args against the tool's input schema without executing."""
    registry = get_registry(request.app)
    tool = next((t for t in registry if t['id'] == body.tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f'Tool {body.tool_id!r} not found')
    unsupported = check_schema_supported(tool['input_schema'])
    if unsupported:
        errors = [{'path': p, 'message': 'unsupported schema'} for p in unsupported]
        return {'valid': False, 'errors': errors, 'args': body.args}
    valid, errors, normalized = validate_args(tool['input_schema'], body.args)
    return {'valid': valid, 'errors': errors, 'args': normalized}


@router.post('/preflight')
def preflight(request: Request, body: PreflightRequest) -> dict:
    """Validate args; return pending token for mutating tools or ready status for safe tools."""
    registry = get_registry(request.app)
    tool = next((t for t in registry if t['id'] == body.tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f'Tool {body.tool_id!r} not found')
    unsupported = check_schema_supported(tool['input_schema'])
    if unsupported:
        errors = [{'path': p, 'message': 'unsupported schema'} for p in unsupported]
        return {'valid': False, 'errors': errors, 'args': body.args}
    valid, errors, normalized = validate_args(tool['input_schema'], body.args)
    if not valid:
        return {'valid': False, 'errors': errors, 'args': body.args}
    method = tool['method']
    path = tool['path']
    if method in MUTATING_METHODS:
        token = pending_store.create(body.tool_id, method, path, normalized)
        return {
            'status': 'pending',
            'valid': True,
            'token': token,
            'tool_id': body.tool_id,
            'method': method,
            'path': path,
            'args': normalized,
            'confirm_required': tool.get('confirm_required', False),
        }
    return {'status': 'ready', 'valid': True, 'args': normalized}


@router.post('/call')
async def call(request: Request, body: CallRequest) -> dict:
    """Execute a tool call. Mutating methods return a pending token for preview-first flow."""
    registry = get_registry(request.app)
    tool = next((t for t in registry if t['id'] == body.tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f'Tool {body.tool_id!r} not found')

    unsupported = check_schema_supported(tool['input_schema'])
    if unsupported:
        errors = [{'path': p, 'message': 'unsupported schema'} for p in unsupported]
        return {'valid': False, 'errors': errors, 'args': body.args}

    valid, errors, normalized = validate_args(tool['input_schema'], body.args)
    if not valid:
        return {'status': 'validation_error', 'valid': False, 'errors': errors, 'args': body.args}

    method = tool['method']
    path = tool['path']

    if method in MUTATING_METHODS:
        token = pending_store.create(body.tool_id, method, path, normalized)
        return {
            'status': 'pending',
            'token': token,
            'tool_id': body.tool_id,
            'method': method,
            'path': path,
            'args': normalized,
            'confirm_required': tool.get('confirm_required', False),
        }

    result = await call_tool(request.app, method, path, normalized)
    return {'status': 'executed', 'result': result}


@router.post('/confirm')
async def confirm(request: Request, body: ConfirmRequest) -> dict:
    """Execute a previously previewed mutating tool call by token."""
    entry = pending_store.pop(body.token)
    if entry is None:
        raise HTTPException(status_code=404, detail='Token not found or expired')

    result = await call_tool(request.app, entry['method'], entry['path'], entry['args'])
    return {'status': 'executed', 'result': result, 'tool_id': entry['tool_id']}


@router.post('/capabilities')
def capabilities(request: Request, body: CapabilitiesRequest) -> list[dict]:
    """Return per-tool schema support status for all or a subset of tools."""
    registry = get_registry(request.app)
    tools = registry if not body.tool_ids else [t for t in registry if t['id'] in body.tool_ids]
    report = []
    for tool in tools:
        unsupported = check_schema_supported(tool['input_schema'])
        report.append(
            {
                'tool_id': tool['id'],
                'supported': len(unsupported) == 0,
                'issues': [{'path': p, 'message': 'unsupported schema'} for p in unsupported],
            }
        )
    return report

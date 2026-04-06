"""MCP API routes — list tools, call tools, confirm pending actions."""

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from core.error_handlers import handle_errors
from core.namespace import get_namespace
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.mcp.executor import build_tool_context, call_tool
from modules.mcp.pending import pending_store
from modules.mcp.registry import MUTATING_METHODS, build_tool_registry
from modules.mcp.validation import check_schema_supported, validate_args

router = APIRouter(prefix='/mcp', tags=['mcp'])


def _request_tool_context(request: Request) -> dict[str, dict[str, str]]:
    return build_tool_context(
        {
            'X-Session-Token': request.headers.get('X-Session-Token') or request.cookies.get('session_token') or '',
            'X-Namespace': request.headers.get('X-Namespace') or get_namespace(),
        },
    )


def get_registry(app: FastAPI) -> list[dict]:
    """Return cached tool registry, building on first call."""
    if not hasattr(app.state, 'mcp_registry'):
        app.state.mcp_registry = build_tool_registry(app)
    return app.state.mcp_registry  # type: ignore[no-any-return]


def _resolve_tool(app: FastAPI, tool_id: str, args: dict) -> tuple[dict, bool, list[dict], dict]:
    """Look up a tool and validate args. Raises 404 if tool not found."""
    registry = get_registry(app)
    tool = next((t for t in registry if t['id'] == tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f'Tool {tool_id!r} not found')
    valid, errors, normalized = validate_args(tool['input_schema'], args)
    return tool, valid, errors, normalized


class ToolRequest(BaseModel):
    """Request body for tool operations."""

    tool_id: str
    args: dict[str, Any] = {}


class ConfirmRequest(BaseModel):
    """Request body for confirming a pending action."""

    token: str


class CapabilitiesRequest(BaseModel):
    """Request body for schema capability check."""

    tool_ids: list[str] = []


@router.get('/tools')
@handle_errors('list MCP tools')
def list_tools(request: Request, user: User = Depends(get_current_user)) -> list[dict]:
    """List all available MCP tools derived from /api/v1 routes."""
    del user
    return get_registry(request.app)


@router.post('/validate')
@handle_errors('validate MCP tool args')
def validate(request: Request, body: ToolRequest, user: User = Depends(get_current_user)) -> dict:
    """Validate tool args against the tool's input schema without executing."""
    del user
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
    if not valid:
        return {'valid': False, 'errors': errors, 'args': body.args}
    return {'valid': valid, 'errors': errors, 'args': normalized}


@router.post('/call')
@handle_errors('call MCP tool')
async def call(request: Request, body: ToolRequest, user: User = Depends(get_current_user)) -> dict:
    """Execute a tool call. Mutating methods return a pending token for preview-first flow."""
    del user
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
    if not valid:
        return {'status': 'validation_error', 'valid': False, 'errors': errors, 'args': body.args}

    method = tool['method']
    path = tool['path']
    context = _request_tool_context(request)

    if method in MUTATING_METHODS:
        token = pending_store.create(body.tool_id, method, path, normalized, context)
        return {
            'status': 'pending',
            'token': token,
            'tool_id': body.tool_id,
            'method': method,
            'path': path,
            'args': normalized,
            'confirm_required': tool.get('confirm_required', False),
        }

    try:
        result = await call_tool(request.app, method, path, normalized, context)
    except ValueError as exc:
        return {
            'status': 'validation_error',
            'valid': False,
            'errors': [{'path': '$', 'message': str(exc), 'validator': 'path_params'}],
            'tool_id': body.tool_id,
            'args': normalized,
        }
    return {'status': 'executed', 'result': result}


@router.post('/confirm')
@handle_errors('confirm MCP tool')
async def confirm(request: Request, body: ConfirmRequest, user: User = Depends(get_current_user)) -> dict:
    """Execute a previously previewed mutating tool call by token."""
    del user
    entry = pending_store.pop(body.token)
    if entry is None:
        raise HTTPException(status_code=404, detail='Token not found or expired')

    try:
        result = await call_tool(request.app, entry.method, entry.path, entry.args, entry.context)
    except ValueError as exc:
        return {
            'status': 'validation_error',
            'valid': False,
            'errors': [{'path': '$', 'message': str(exc), 'validator': 'path_params'}],
            'tool_id': entry.tool_id,
            'args': entry.args,
        }
    return {'status': 'executed', 'result': result, 'tool_id': entry.tool_id}


@router.post('/capabilities')
@handle_errors('check MCP capabilities')
def capabilities(request: Request, body: CapabilitiesRequest, user: User = Depends(get_current_user)) -> list[dict]:
    """Return per-tool schema support status for all or a subset of tools."""
    del user
    registry = get_registry(request.app)
    tools = registry if not body.tool_ids else [t for t in registry if t['id'] in body.tool_ids]
    return [
        {
            'tool_id': tool['id'],
            'supported': not (unsupported := check_schema_supported(tool['input_schema'])),
            'issues': [{'path': p, 'message': 'unsupported schema'} for p in unsupported],
        }
        for tool in tools
    ]

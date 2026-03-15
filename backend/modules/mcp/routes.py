"""MCP API routes — list tools, call tools, confirm pending actions."""

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

from modules.mcp.executor import call_tool
from modules.mcp.pending import pending_store
from modules.mcp.registry import MUTATING_METHODS, build_tool_registry
from modules.mcp.validation import check_schema_supported, validate_args

router = APIRouter(prefix='/mcp', tags=['mcp'])


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
def list_tools(request: Request) -> list[dict]:
    """List all available MCP tools derived from /api/v1 routes."""
    return get_registry(request.app)


@router.post('/validate')
def validate(request: Request, body: ToolRequest) -> dict:
    """Validate tool args against the tool's input schema without executing."""
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
    if not valid:
        return {'valid': False, 'errors': errors, 'args': body.args}
    return {'valid': valid, 'errors': errors, 'args': normalized}


@router.post('/call')
async def call(request: Request, body: ToolRequest) -> dict:
    """Execute a tool call. Mutating methods return a pending token for preview-first flow."""
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
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
    return [
        {
            'tool_id': tool['id'],
            'supported': not (unsupported := check_schema_supported(tool['input_schema'])),
            'issues': [{'path': p, 'message': 'unsupported schema'} for p in unsupported],
        }
        for tool in tools
    ]

"""MCP API routes — list tools, call tools, confirm pending actions."""

from typing import Any

from core.namespace import get_namespace
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from backend_core.error_handlers import handle_errors
from modules.auth.dependencies import get_current_user
from modules.auth.models import User
from modules.mcp.executor import build_tool_context, call_tool
from modules.mcp.models import MCPToolDefinition
from modules.mcp.pending import pending_store
from modules.mcp.registry import build_tool_registry

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _coerce_tool(item: MCPToolDefinition | dict[str, Any]) -> MCPToolDefinition:
    return MCPToolDefinition.coerce(item)


def _request_tool_context(request: Request) -> dict[str, dict[str, str]]:
    return build_tool_context(
        {
            "X-Session-Token": request.headers.get("X-Session-Token") or request.cookies.get("session_token") or "",
            "X-Namespace": request.headers.get("X-Namespace") or get_namespace(),
        },
    )


def get_registry(app: FastAPI) -> list[MCPToolDefinition]:
    """Return cached tool registry, building on first call."""
    if not hasattr(app.state, "mcp_registry"):
        app.state.mcp_registry = build_tool_registry(app)
    registry = getattr(app.state, "mcp_registry")
    if not isinstance(registry, list):
        app.state.mcp_registry = []
        return []
    normalized = [_coerce_tool(item) for item in registry]
    app.state.mcp_registry = normalized
    return normalized


def _resolve_tool(app: FastAPI, tool_id: str, args: dict) -> tuple[MCPToolDefinition, bool, list[dict], dict]:
    """Look up a tool and validate args. Raises 404 if tool not found."""
    registry = get_registry(app)
    tool = next((t for t in registry if t.id == tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id!r} not found")
    valid, errors, normalized = tool.validate_arguments(args)
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


@router.get("/tools")
@handle_errors("list MCP tools")
def list_tools(request: Request, user: User = Depends(get_current_user)) -> list[MCPToolDefinition]:
    """List all available MCP tools derived from /api/v1 routes."""
    del user
    return get_registry(request.app)


@router.post("/validate")
@handle_errors("validate MCP tool args")
def validate(request: Request, body: ToolRequest, user: User = Depends(get_current_user)) -> dict:
    """Validate tool args against the tool's input schema without executing."""
    del user
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
    if not valid:
        return {"valid": False, "errors": errors, "args": body.args}
    return {"valid": valid, "errors": errors, "args": normalized}


@router.post("/call")
@handle_errors("call MCP tool")
async def call(request: Request, body: ToolRequest, user: User = Depends(get_current_user)) -> dict:
    """Execute a tool call. Mutating methods return a pending token for preview-first flow."""
    del user
    tool, valid, errors, normalized = _resolve_tool(request.app, body.tool_id, body.args)
    if not valid:
        return tool.validation_error_response(errors, body.args)

    context = _request_tool_context(request)

    if tool.method.is_mutating:
        token = pending_store.create(tool.id, tool.method, tool.path, normalized, context)
        return tool.pending_response(token, normalized)

    try:
        result = await call_tool(request.app, tool.method, tool.path, normalized, context)
    except ValueError as exc:
        return tool.path_param_error_response(str(exc), normalized)
    return tool.executed_response(result)


@router.post("/confirm")
@handle_errors("confirm MCP tool")
async def confirm(request: Request, body: ConfirmRequest, user: User = Depends(get_current_user)) -> dict:
    """Execute a previously previewed mutating tool call by token."""
    del user
    entry = pending_store.pop(body.token)
    if entry is None:
        raise HTTPException(status_code=404, detail="Token not found or expired")

    tool = next((item for item in get_registry(request.app) if item.id == entry.tool_id), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {entry.tool_id!r} not found")

    try:
        result = await call_tool(request.app, entry.method, entry.path, entry.args, entry.context)
    except ValueError as exc:
        return tool.path_param_error_response(str(exc), entry.args)
    response = tool.executed_response(result)
    response["tool_id"] = entry.tool_id
    return response


@router.post("/capabilities")
@handle_errors("check MCP capabilities")
def capabilities(request: Request, body: CapabilitiesRequest, user: User = Depends(get_current_user)) -> list[dict]:
    """Return per-tool schema support status for all or a subset of tools."""
    del user
    registry = get_registry(request.app)
    tools = registry if not body.tool_ids else [t for t in registry if t["id"] in body.tool_ids]
    return [tool.capability_report() for tool in tools]

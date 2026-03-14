"""MCP module — auto-expose /api/v1 routes as tools with preview-first execution."""

from modules.mcp.routes import router

__all__ = ['router']

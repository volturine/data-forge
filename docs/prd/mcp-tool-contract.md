# MCP Tool Contract

Maintainer reference for how `/api/v1` routes are exposed as MCP tools, how AI agents consume them, and how to safely add or change tools without drift.

---

## Overview

The MCP module (`backend/modules/mcp/`) auto-discovers FastAPI routes and exposes them as structured tool definitions to AI agents. The pipeline is:

1. Routes opt in with `@deterministic_tool`
2. At first request, `build_tool_registry()` reads the OpenAPI schema and builds a tool list
3. The registry is cached on `app.state.mcp_registry` for the process lifetime
4. AI agents call tools through `/api/v1/mcp/call`, which validates args, routes the request in-process via httpx ASGI transport, and returns structured results

Routes without `@deterministic_tool` are invisible to MCP. Routes under `/mcp/` and `/ai/chat` are always excluded.

---

## Module Layout

| File | Responsibility |
|------|----------------|
| `decorators.py` | `@deterministic_tool` — opt-in marker |
| `registry.py` | OpenAPI → tool definitions, schema resolution, confirm patterns |
| `validation.py` | JSON Schema validation, default/const application, schema support checks |
| `executor.py` | In-process route invocation via httpx `ASGITransport` |
| `pending.py` | Token store for preview-then-confirm flow (mutating methods) |
| `routes.py` | MCP API endpoints: `/tools`, `/call`, `/confirm`, `/validate`, `/capabilities` |

---

## Registry Shape

Each tool definition is a dict with this shape:

```python
{
    'id': 'endpoint_function_name',       # Python function name from @deterministic_tool
    'method': 'GET',                       # HTTP method (uppercase)
    'path': '/api/v1/resource/{id}',       # Path template with {param} placeholders
    'description': 'Human-readable text',  # From docstring/summary/description
    'safety': 'safe',                      # 'safe' (GET/HEAD/OPTIONS) or 'mutating'
    'confirm_required': False,             # True if method+path matches CONFIRM_REQUIRED_PATTERNS
    'input_schema': {                      # Flat JSON Schema — all args at top level
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},      # Path params
            'limit': {'type': 'integer'},  # Query params
            'payload': { ... },            # Request body (if any)
        },
        'required': ['id', 'payload'],
        'additionalProperties': False,     # Always false — rejects unknown args
    },
    'arg_metadata': {                      # Placement hints for prompt engineering
        'path': [{'name': 'id', 'required': True, 'description': '...', 'schema': {...}}],
        'query': [{'name': 'limit', 'required': False, 'description': '...', 'schema': {...}}],
        'payload': {                       # None if no request body
            'required': True,
            'content_type': 'application/json',
            'description': '...',
        },
    },
    'tags': ['datasource'],
}
```

### Key design decisions

- **`additionalProperties: false`** on every tool schema — AI agents that send unknown keys get a validation error immediately rather than a silent 422 later.
- **`arg_metadata`** exposes where each arg goes (path / query / body) so prompt templates can describe exact placement without hardcoding per-tool knowledge.
- **`id`** is the Python function name, not an auto-generated slug. This keeps tool IDs stable across URL refactors.

---

## Argument Placement

All arguments are passed flat in `args` (a single JSON object). The executor separates them by role:

| Role | How it's identified | Where it goes |
|------|---------------------|---------------|
| **Path** | Matches `{param}` placeholder in `tool.path` | URL-interpolated with percent-encoding |
| **Query** | Remaining keys after path params (excluding `payload`) | `?key=value` query string |
| **Payload** | The `payload` key specifically | JSON request body (POST/PUT/PATCH only) |

### Path interpolation

`executor._interpolate_path()` replaces `{param}` placeholders from `args`. Missing path params raise `ValueError`, which the `/call` route converts to a structured `validation_error` response (not a 404/422).

### Example

For a tool with `path: /api/v1/datasource/{datasource_id}` and method `PUT`:

```json
{
    "tool_id": "update_datasource",
    "args": {
        "datasource_id": "abc-123",
        "limit": 10,
        "payload": {"name": "New Name"}
    }
}
```

- `datasource_id` → interpolated into URL: `/api/v1/datasource/abc-123`
- `limit` → query string: `?limit=10`
- `payload` → JSON body: `{"name": "New Name"}`

---

## Validation and Error Behavior

### Schema validation (pre-execution)

Every `/call` validates `args` against `tool.input_schema` using `jsonschema` before any HTTP request is made. If invalid:

```json
{
    "status": "validation_error",
    "valid": false,
    "errors": [
        {
            "path": "$",
            "message": "'name' is a required property. Provide all required fields.",
            "validator": "required"
        }
    ],
    "args": { ... }
}
```

Error messages are enhanced with actionable hints per validator type:

| Validator | Hint appended |
|-----------|---------------|
| `required` | "Provide all required fields." |
| `additionalProperties` | "Remove unknown fields or use documented parameter names." |
| `enum` | "Use one of the documented enum values." |
| `type` | "Use the documented JSON type for this field." |
| Format/constraint | "Check schema constraints for this field." |

### Path parameter errors (at execution)

If a path `{param}` is missing from args at execution time (schema didn't catch it), the executor raises `ValueError`. The `/call` route wraps this as:

```json
{
    "status": "validation_error",
    "valid": false,
    "errors": [{"path": "$", "message": "Missing required path parameter(s): item_id", "validator": "path_params"}],
    "tool_id": "broken_tool",
    "args": { ... }
}
```

This is a structured response (HTTP 200), not a 404 or 422 — so AI agents can parse and repair the exact missing parameter.

### Default/const application

After validation passes, `apply_defaults()` fills missing properties from `default` and `const` values in the schema. Nested objects are recursively populated. This means AI agents don't need to explicitly pass default values.

### Schema support checks

At registry build time, `check_schema_supported()` walks every tool's schema and raises `ValueError` if any unsupported JSON Schema keywords are present. This is a **fail-fast at startup** — no tool with an unsupported schema can enter the registry.

The `/capabilities` endpoint lets callers check support status per-tool at runtime.

---

## Confirm Flow (Mutating Methods)

All mutating methods (POST, PUT, PATCH, DELETE) go through a two-step preview-then-confirm flow:

```
Agent → POST /mcp/call {tool_id, args}
    ← {status: "pending", token: "abc...", confirm_required: true/false, ...}

Agent reviews the preview, then:
Agent → POST /mcp/confirm {token: "abc..."}
    ← {status: "executed", result: {...}, tool_id: "..."}
```

### Token behavior

- Tokens are generated via `secrets.token_urlsafe(24)`
- Stored in-memory in `PendingStore` with a **300-second TTL**
- Single-use: `pop()` removes the token on confirm
- Expired or unknown tokens return HTTP 404

### `confirm_required` flag

`CONFIRM_REQUIRED_PATTERNS` in `registry.py` defines which method+path combinations require explicit user confirmation before the AI agent proceeds. Currently:

```python
CONFIRM_REQUIRED_PATTERNS = [
    ('DELETE', r'^/api/v1/datasource/'),
    ('DELETE', r'^/api/v1/scheduler/'),
    ('DELETE', r'^/api/v1/healthchecks/'),
    ('DELETE', r'^/api/v1/analysis/'),
]
```

The `confirm_required` field is informational — the pending-token flow applies to **all** mutating methods regardless. The flag tells the frontend/AI whether to prompt the user before confirming.

---

## Prompt Coupling

The chat system (`modules/chat/routes.py`) builds a tool system message from the registry. It uses `arg_metadata` to describe each parameter's placement:

```
- update_datasource [PUT]: Update a datasource
  Parameters:
    datasource_id (string, required, path): The datasource ID
    payload (object, required, body): Request body
      content_type: application/json
```

### Why `arg_metadata` exists

Without it, the prompt would only have the flat `input_schema` — the AI couldn't know whether `datasource_id` goes in the URL, the query string, or the body. The metadata eliminates this ambiguity and prevents drift between the registry and the prompt template.

### Fallback behavior

If `arg_metadata` is missing or `None`, `_format_fallback_param_details()` falls back to describing params from the raw `input_schema` without placement hints.

---

## Opting In: The `@deterministic_tool` Decorator

To expose a route as an MCP tool:

```python
from modules.mcp.decorators import deterministic_tool

@router.get('/{datasource_id}')
@deterministic_tool
async def get_datasource(datasource_id: str, session: SessionDep) -> DatasourceResponse:
    ...
```

The decorator sets `fn.__mcp_tool__ = True`. The registry scans all `APIRoute` instances and only includes routes where the endpoint has this attribute.

### Rules

- Place `@deterministic_tool` directly above the function, below the `@router` decorator
- The function **name** becomes the tool `id` — choose stable, descriptive names
- The route's OpenAPI description/summary becomes the tool `description`
- If the route has a Pydantic request body, it appears as `payload` in the schema

---

## Maintainer Checklist

### Adding a new tool

1. Add `@deterministic_tool` to the route endpoint function
2. Ensure the function name is a stable, descriptive identifier (it becomes the tool `id`)
3. Write a clear `description` or `summary` on the route — this is what the AI sees
4. Verify path parameters match `{param}` in the URL template exactly
5. If the route accepts a request body, confirm the Pydantic model resolves cleanly in OpenAPI
6. Run `just verify` — `build_tool_registry()` will raise `ValueError` at test time if the schema has unsupported keywords
7. Check the tool appears in `GET /api/v1/mcp/tools` with correct `arg_metadata`
8. If the tool is a destructive DELETE, add a pattern to `CONFIRM_REQUIRED_PATTERNS`

### Changing an existing tool

1. **Renaming the function** changes the tool `id` — this breaks any saved prompts or chat history referencing the old name
2. **Changing path params** — verify `arg_metadata.path` updates accordingly (it's auto-derived from OpenAPI)
3. **Adding required fields** — existing AI callers will get `validation_error` until they learn the new schema
4. **Removing fields** — if `additionalProperties: false` (it is), old callers sending removed fields will get `validation_error`
5. Run `just verify` after any change

### Removing a tool

1. Remove `@deterministic_tool` from the endpoint
2. The tool disappears from the registry on next startup — no migration needed
3. If it was in `CONFIRM_REQUIRED_PATTERNS`, remove the pattern

### Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Forgot `@deterministic_tool` | Tool missing from `/mcp/tools` | Add the decorator |
| Function name changed | AI calls old tool ID, gets 404 | Keep names stable or update prompts |
| Path param name mismatch | `Missing required path parameter(s)` error | Match `{param}` name to function arg name |
| Unsupported schema keyword (e.g. `x-vendor-ext`) | `ValueError` at startup | Remove the keyword or add it to `_SUPPORTED_KEYWORDS` |
| Body model uses unsupported JSON Schema features | `ValueError` at startup | Simplify the Pydantic model |

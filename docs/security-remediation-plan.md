# Security Remediation Plan

## Goal

Fix the confirmed audit findings in a safe order, keep the app working throughout, and verify the full stack with `just verify` after the changes land.

## Step 1 — Frontend output sanitization

- [ ] Add `dompurify` to the frontend with `bun add dompurify @types/dompurify`
- [ ] Sanitize markdown output in `frontend/src/lib/utils/markdown.ts`
- [ ] Add regression tests for script tags, inline event handlers, and `javascript:` links
- [ ] Keep `ChatPanel.svelte` rendering path unchanged so all chat markdown flows through one sanitizer

## Step 2 — Secret transport and secret exposure

- [ ] Move AI model listing / connection checks off URL query params and into request bodies
- [ ] Update frontend callers in `frontend/src/lib/api/ai.ts` and `frontend/src/lib/api/chat.ts`
- [ ] Update backend AI/chat routes to accept typed request bodies instead of query params
- [ ] Stop returning plaintext secrets from `GET /api/v1/settings`
- [ ] Mask secret fields in settings responses and preserve stored values when masked placeholders are submitted back unchanged
- [ ] Update chat/settings frontend state so masked global keys do not get copied into plaintext local state unless the user explicitly enters a new key

## Step 3 — Secret storage at rest

- [ ] Replace XOR-based settings secret storage with authenticated encryption
- [ ] Encrypt SMTP password, Telegram token, and OpenRouter key consistently
- [ ] Encrypt chat session API keys at rest
- [ ] Keep read/update helpers centralized so all secret fields follow one contract
- [ ] Add tests proving DB rows no longer store plaintext secrets

## Step 4 — Authentication and internal tool execution

- [ ] Require authenticated users on chat routes
- [ ] Require authenticated users on MCP routes
- [ ] Forward auth/session context when MCP executes internal in-process tool calls
- [ ] Preserve namespace/session headers needed by downstream protected routes
- [ ] Add route tests covering authenticated access expectations and MCP/chat model flows

## Step 5 — Logging redaction

- [ ] Redact sensitive request/response bodies in backend request logging
- [ ] Redact password and secret fields in frontend audit logging
- [ ] Add regression tests so password fields are never captured in client audit events
- [ ] Ensure `GET /settings` responses are logged only in masked form

## Step 6 — Compute execution hardening

- [ ] Harden expression parsing so unsafe object-model access is rejected before evaluation
- [ ] Harden inline UDF execution in `with_columns.py` with the same forbidden-pattern guardrails
- [ ] Remove obvious reflection / dunder escape paths from accepted code
- [ ] Add regression tests for blocked dangerous payloads

## Step 7 — Verification

- [ ] Run targeted backend and frontend tests for all touched areas
- [ ] Run `just verify`
- [ ] Run reviewer pass on the final diff
- [ ] Update this document with completion status and any follow-up work if something remains out of scope

## Why

The compute API redesign is defined in `docs/pipeline-compute.md`, but the frontend and backend still emit or accept incomplete tab payloads. This mismatch causes build failures like "missing output configuration" and blocks compute builds.

## What Changes

- Enforce a single, explicit pipeline tab schema across frontend state, API payloads, and backend validation.
- Require `output` configuration for every tab and ensure `output.output_datasource_id` is always present.
- Ensure tab-to-tab dependencies use `datasource.id` + `analysis_tab_id` consistently.
- Align error handling and validation messages to the spec so failures are clear and early.

## Capabilities

### New Capabilities
- `pipeline-compute-schema`: Define the canonical analysis pipeline tab schema and required fields used by frontend and backend.

### Modified Capabilities
- (none)

## Impact

- Backend compute payload validation and build orchestration.
- Frontend pipeline builder/editor state and request payloads.
- API responses and error messages for compute build failures.

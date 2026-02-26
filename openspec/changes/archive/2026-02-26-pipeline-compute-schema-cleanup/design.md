## Context

The canonical pipeline tab schema is described in `docs/pipeline-compute.md`, but the frontend pipeline builder and backend validation are not aligned with it. In particular, tabs can be emitted without `output` or `output.output_datasource_id`, leading to build failures at compute time. The backend also needs to resolve tab-to-tab dependencies consistently via `datasource.id` + `analysis_tab_id`.

## Goals / Non-Goals

**Goals:**
- Define a single, explicit tab schema contract that frontend and backend adhere to.
- Validate required fields early (before build) and return clear errors.
- Ensure tab dependencies are consistently represented and resolved.

**Non-Goals:**
- Redesign compute execution or add new compute operations.
- Change runtime behavior of the Polars engine beyond schema validation and payload shape.

## Decisions

- **Adopt the tab schema in `docs/pipeline-compute.md` as canonical.** This document already describes the intended shape; aligning both ends removes ambiguity.
- **Require `output` for every tab and `output.output_datasource_id` always.** Build failures show this is a hard requirement, so enforce it in frontend state and backend validation.
- **Standardize dependency wiring via `datasource.id` + `analysis_tab_id`.** This preserves the ability to chain tabs as a single lazyframe plan and matches current backend resolution.
- **Surface validation errors at save/build request time.** Failing early prevents expensive compute attempts and yields actionable errors.

## Risks / Trade-offs

- **Breaking changes for existing analyses** → Provide a migration path in the UI or backend normalization to fill missing `output` fields.
- **Frontend/backend drift persists** → Add shared schema definitions or tests to ensure payloads match the spec.
- **Strict validation blocks edge cases** → Define explicit defaults and document required fields to reduce ambiguity.

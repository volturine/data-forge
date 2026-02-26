## 1. Schema alignment

- [x] 1.1 Identify current frontend pipeline tab state shape and compare to `docs/pipeline-compute.md`
- [x] 1.2 Identify backend validation and payload builders that accept tab schema
- [x] 1.3 Define shared schema defaults for `output` and `datasource` fields

## 2. Frontend updates

- [x] 2.1 Update pipeline tab creation to always include `output` with `output_datasource_id`
- [x] 2.2 Ensure tab dependency wiring sets `datasource.id` and `datasource.analysis_tab_id`
- [x] 2.3 Add frontend validation/error messaging for missing required fields

## 3. Backend validation

- [x] 3.1 Enforce `output` and `output.output_datasource_id` in build/save validation
- [x] 3.2 Enforce `datasource` and `datasource.id` requirements for tabs
- [x] 3.3 Normalize or migrate existing analyses missing required fields

## 4. Tests and verification

- [x] 4.1 Add backend tests for tab schema validation errors
- [x] 4.2 Add frontend tests (or checks) ensuring payloads include required fields
- [x] 4.3 Run `just verify` and address any failures

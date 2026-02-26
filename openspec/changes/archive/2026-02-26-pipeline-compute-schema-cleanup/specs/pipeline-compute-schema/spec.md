## ADDED Requirements

### Requirement: Tab output configuration is required
Each analysis pipeline tab MUST include an `output` object with `output_datasource_id`, `datasource_type`, `format`, and `filename` fields.

#### Scenario: Missing output object
- **WHEN** a tab is submitted without an `output` object
- **THEN** the request fails with a validation error stating output configuration is required

#### Scenario: Missing output datasource id
- **WHEN** a tab is submitted with `output` but without `output.output_datasource_id`
- **THEN** the request fails with a validation error stating `output.output_datasource_id` is required

### Requirement: Tab datasource configuration is required
Each analysis pipeline tab MUST include a `datasource` object with `id` and `analysis_tab_id` fields.

#### Scenario: Missing datasource object
- **WHEN** a tab is submitted without a `datasource` object
- **THEN** the request fails with a validation error stating datasource configuration is required

#### Scenario: Missing datasource id
- **WHEN** a tab is submitted with `datasource` but without `datasource.id`
- **THEN** the request fails with a validation error stating `datasource.id` is required

### Requirement: Tab dependency wiring follows output datasource ids
If a tab depends on another tab, the dependent tab MUST set `datasource.id` to the upstream tab's `output.output_datasource_id` and set `datasource.analysis_tab_id` to the upstream tab's `id`.

#### Scenario: Tab depends on upstream output
- **WHEN** a dependent tab references an upstream tab output
- **THEN** the payload includes `datasource.id` equal to the upstream `output.output_datasource_id` and `datasource.analysis_tab_id` equal to the upstream `id`

### Requirement: Validation errors are surfaced before compute builds
The system MUST validate tab schema requirements before compute build execution and return errors that identify the missing or invalid fields.

#### Scenario: Early validation failure
- **WHEN** a build request includes a tab missing required fields
- **THEN** the request fails before compute starts and returns the specific missing field names

# Bugs and Issues and feature requests

---

the scheduling ui is still bit confusing.. the creation of schedule is right.. but the schedule table is not.. as it seems one schedule could be of many types but it cant.. also in create schedule in schedule tab i cant create schedules on raw datasets (datasets that have not been created inside analysis) but in lineage tab i can fix these issues

---

excel upload is bit buggy.. range selection is not supported by the fronend at all. look into how we handle excel upload through and through.

---

the way we handle datasource.source_type is bit weird.. prone to forgetfulness for example in

```
def _extract_schema(datasource: DataSource, sheet_name: str | None = None) -> SchemaInfo:
    if datasource.source_type == 'analysis':
        raise DataSourceValidationError(
            'Schema extraction not supported for analysis datasources',
            details={'datasource_id': datasource.id},
        )

    if datasource.source_type == 'database':
....
```

we didnt have duckdb i had to add it manualy.. we should have a more robust way to handle this.. datasource type should be an enum.. also we should have a more robust way to handle unsupported datasource types instead of just forgetting about it and running into issues later on when we try to use it. also reusable code is key i had to refactor this:

```
def _extract_schema(datasource: DataSource, sheet_name: str | None = None) -> SchemaInfo:
    if datasource.source_type == 'analysis':
        raise DataSourceValidationError(
            'Schema extraction not supported for analysis datasources',
            details={'datasource_id': datasource.id},
        )

    if datasource.source_type == 'database':
        connection_string = datasource.config['connection_string']
        query = datasource.config['query']
        try:
            frame = pl.read_database(query, connection_string)
        except Exception as e:
            raise DataSourceConnectionError(
                'Failed to query database datasource',
                details={'datasource_id': datasource.id, 'source_type': datasource.source_type},
            ) from e
        schema = frame.schema
        row_count = frame.height

        # Get first non-null value for each column
        sample_values = _get_first_non_null_samples_eager(frame)

        columns = [
            ColumnSchema(
                name=name,
                dtype=str(dtype),
                nullable=True,
                sample_value=sample_values.get(name),
            )
            for name, dtype in schema.items()
        ]

        return SchemaInfo(columns=columns, row_count=row_count)

    if datasource.source_type == 'file':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        if sheet_name:
            config = {**config, 'sheet_name': sheet_name}
        try:
            lazy = load_datasource(config)
        except Exception as e:
            raise DataSourceConnectionError(
                'Failed to load file datasource',
                details={'datasource_id': datasource.id, 'source_type': datasource.source_type},
            ) from e

    if datasource.source_type == 'duckdb':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        try:
            lazy = load_datasource(config)
        except Exception as e:
            raise DataSourceConnectionError(
                'Failed to load DuckDB datasource',
                details={'datasource_id': datasource.id, 'source_type': datasource.source_type},
            ) from e

    if datasource.source_type == 'iceberg':
        config = {
            'source_type': datasource.source_type,
            **datasource.config,
        }
        try:
            lazy = load_datasource(config)
        except Exception as e:
            raise DataSourceConnectionError(
                'Failed to load Iceberg datasource',
                details={'datasource_id': datasource.id, 'source_type': datasource.source_type},
            ) from e

    schema = lazy.collect_schema()
    row_count = lazy.select(pl.len()).collect().item()
    sheet_names = None

    # Get first non-null value for each column
    sample_values = _get_first_non_null_samples(lazy)

    columns = [
        ColumnSchema(
            name=name,
            dtype=str(dtype),
            nullable=True,
            sample_value=sample_values.get(name),
        )
        for name, dtype in schema.items()
    ]

    return SchemaInfo(columns=columns, row_count=row_count, sheet_names=sheet_names)
```

before each if had this a duplicate:

```
    schema = lazy.collect_schema()
    row_count = lazy.select(pl.len()).collect().item()
    sheet_names = None

    # Get first non-null value for each column
    sample_values = _get_first_non_null_samples(lazy)

    columns = [
        ColumnSchema(
            name=name,
            dtype=str(dtype),
            nullable=True,
            sample_value=sample_values.get(name),
        )
        for name, dtype in schema.items()
    ]

    return SchemaInfo(columns=columns, row_count=row_count, sheet_names=sheet_names)
```

---

also i think duckdb and iceberg datasources should be in the same category as file datasources since they are both file based and not database connections.. this is bit confusing and also we should have a more robust way to handle different datasource types instead of just relying on if statements everywhere.. maybe we can have a registry of datasource handlers or something like that to make it more extensible and less error prone.

---

build comparison ui should be inside datasources tab.. and not in builds.. and it should be as comparison of metadata for both builds but with ability to also have the two datasets side by side with ability to do column mapping and then show the diff of the two datasets based on the column mapping.. this will be super useful for users to understand what changed between two builds and also to validate if the new build is correct or not. also this will be super useful for debugging issues with datasource connections and schema extraction since we can compare a working build with a non working build and see what the differences are in terms of metadata and also in terms of actual data if we have the ability to do that. we could see each row of the two datasets side by side.

---

one should be only able to add one row count healthckeck per datasource.. also we should have more healthcheck options like column count, null value percentage, duplicate value percentage, etc.. anything that can be lazily evaluated on the datasource and can give us insights into the health of the datasource.. also should be able to specify which healthcheck is critical and which is not.. critical healthcheks will fail the build if they fail and non critical healthchecks will just give us warnings but will not fail the build. right now all healthcheks are not critical as they are built after.. critical healthcheks should be built before the write phase and if they fail they should prevent the build from being written to the dataset

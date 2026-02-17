# Query Plan Coverage in Polars vs PySpark

## Summary

Polars query plans are strictly a **lazy** construct (`LazyFrame.explain()`); eager operations (`collect`, `map_elements` on a materialized DataFrame, or custom handlers that call `collect()`) are **not part of the lazy plan**. PySpark’s `explain()` includes UDF operators (`BatchEvalPythonExec`, `ArrowEvalPythonExec`) inside the plan because Spark remains lazy and represents Python UDFs as execution nodes in its physical plan.

Because our pipeline includes eager steps (notification/AI), a single native Polars plan cannot include those steps. The fix is to produce a **composite/top-level plan** that concatenates lazy segments with explicit eager barriers.

## Polars Constraints (Lazy-only Plans)

- `LazyFrame.explain()` produces a plan for **lazy** execution only.
- `collect()` materializes and ends the lazy plan. Anything after `collect()` is outside the plan.
- Python UDFs expressed as `map_elements` do appear in the lazy plan but are opaque to optimizations.

References:
- https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.explain.html
- https://docs.pola.rs/user-guide/lazy/query-plan/
- https://docs.pola.rs/user-guide/lazy/execution
- https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.map_elements.html

## PySpark Behavior (UDFs in Plan)

PySpark’s `DataFrame.explain()` includes UDF operators in the physical plan (e.g., `BatchEvalPythonExec`, `ArrowEvalPythonExec`). UDFs are represented explicitly as plan nodes, enabling end-to-end plan visibility (even if they are optimization barriers).

References:
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.explain.html
- https://github.com/apache/spark/blob/master/sql/core/src/main/scala/org/apache/spark/sql/execution/python/BatchEvalPythonExec.scala

## Implementation in This Repo

### Composite Plan Approach

We segment the pipeline at eager steps and compute a lazy plan per segment:

1. **Lazy segment**: all steps until the next eager op → `LazyFrame.explain()`.
2. **Eager barrier**: explicit marker for operations that call `collect()` (notification/AI).
3. **Next lazy segment**: restart from `df.lazy()` and repeat.

### Result Format

The top-level plan is rendered by concatenating segment plans and inserting a barrier block:

```
<lazy plan segment 1>

-- EAGER STEP (notification) / MATERIALIZE --

<lazy plan segment 2>
```

Both optimized and unoptimized plans are built this way and attached to `query_plans`.

### Why This Matches Polars Reality

- It preserves the **true lazy plans** produced by Polars.
- It explicitly documents **materialization boundaries** where Polars cannot represent eager work.
- It creates a **single top-level plan** for user debugging that includes all steps (lazy + eager).

## Notes

- This does **not** make eager steps optimizable; it only surfaces them in the plan.
- If an eager step could be expressed as `map_batches`, it could remain inside a lazy plan, but that is not the case for notification/AI steps that require full materialization and external I/O.

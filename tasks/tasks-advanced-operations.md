# Advanced Polars Operations Implementation Tasks

**Overall Completion: 0%**

This task file tracks the implementation of 6 advanced Polars data transformation operations that extend the platform's capabilities beyond the core 8 operations.

---

## Backend Implementation (0% Complete)

### 1. Pivot Operation (0% Complete)

**Purpose:** Transform data from long to wide format (rows → columns)

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `pivot` operation handler in `_apply_step()` method
- [ ] Support index columns (rows to preserve)
- [ ] Support pivot column (column to spread)
- [ ] Support values column (data to fill)
- [ ] Support aggregation function (if multiple values per cell)
- [ ] Handle null values in pivot results

**Example Usage:**
```python
# Transform sales data from long to wide
df.pivot(index=['date'], columns='product', values='sales', aggregate_function='sum')
```

---

### 2. Time Series Operations (0% Complete)

**Purpose:** Date/time manipulation and feature extraction

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `timeseries` operation handler in `_apply_step()` method
- [ ] Extract year, month, day, hour, minute, second
- [ ] Calculate date differences
- [ ] Add/subtract time periods (days, weeks, months)
- [ ] Date formatting/parsing
- [ ] Business day calculations
- [ ] Week of year, day of week, quarter extraction

**Example Operations:**
- Extract year: `col("date").dt.year()`
- Add days: `col("date") + timedelta(days=7)`
- Date diff: `col("end_date") - col("start_date")`

---

### 3. String Methods (0% Complete)

**Purpose:** Advanced string manipulation beyond basic concatenation

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `string_transform` operation handler in `_apply_step()` method
- [ ] String case transformations (upper, lower, title, capitalize)
- [ ] Substring extraction (slice, split, extract)
- [ ] Pattern matching (regex, replace)
- [ ] Trimming (strip, lstrip, rstrip)
- [ ] Length calculation
- [ ] Padding (ljust, rjust, zfill)
- [ ] String checks (startswith, endswith, contains)

**Example Operations:**
- Uppercase: `col("name").str.to_uppercase()`
- Extract: `col("email").str.extract(r'@(.+)$', 1)`
- Replace: `col("text").str.replace_all('old', 'new')`

---

### 4. Fill Null (0% Complete)

**Purpose:** Handle missing data with various strategies

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `fill_null` operation handler in `_apply_step()` method
- [ ] Fill with literal value
- [ ] Forward fill (propagate last valid value)
- [ ] Backward fill (propagate next valid value)
- [ ] Fill with mean/median/mode
- [ ] Fill with column-specific values
- [ ] Drop rows with nulls
- [ ] Drop columns with nulls above threshold

**Example Operations:**
- Literal: `df.fill_null(0)`
- Forward fill: `df.fill_null(strategy='forward')`
- Mean: `df.fill_null(col('age').mean())`

---

### 5. Duplicate Removal (0% Complete)

**Purpose:** Remove duplicate rows based on column criteria

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `deduplicate` operation handler in `_apply_step()` method
- [ ] Remove duplicates across all columns
- [ ] Remove duplicates based on subset of columns
- [ ] Keep first occurrence
- [ ] Keep last occurrence
- [ ] Keep none (drop all duplicates)
- [ ] Count duplicates (optional)

**Example Operations:**
- All columns: `df.unique()`
- Subset: `df.unique(subset=['email'])`
- Keep last: `df.unique(subset=['id'], keep='last')`

---

### 6. Explode (0% Complete)

**Purpose:** Transform list/array columns into multiple rows

**Location:** `backend/modules/compute/engine.py`

**Tasks:**
- [ ] Add `explode` operation handler in `_apply_step()` method
- [ ] Explode single list column
- [ ] Explode multiple list columns simultaneously
- [ ] Handle null values in lists
- [ ] Handle empty lists
- [ ] Preserve row context during explosion

**Example Operations:**
- Single: `df.explode('tags')`
- Multiple: `df.explode(['tags', 'categories'])`

---

## Frontend Implementation (0% Complete)

### 7. PivotConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/PivotConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Index columns selector (multi-select)
- [ ] Pivot column selector (single column)
- [ ] Values column selector (single column)
- [ ] Aggregation function dropdown (sum, mean, count, min, max, first, last)
- [ ] Preview example transformation
- [ ] Save/Cancel handlers
- [ ] Type validation (ensure numeric columns for aggregation)

**UI Elements:**
- 3 column selectors (index, pivot, values)
- Aggregation function dropdown
- Help text with examples

---

### 8. TimeSeriesConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/TimeSeriesConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Source column selector (date/datetime columns only)
- [ ] Operation type selector (extract, add, subtract, format, diff)
- [ ] Dynamic parameters based on operation:
  - Extract: year/month/day/hour/minute/second/quarter/week/dayofweek
  - Add/Subtract: value + unit (days/weeks/months/years)
  - Format: format string input
  - Diff: second column selector
- [ ] New column name input
- [ ] Preview example output
- [ ] Save/Cancel handlers

**UI Elements:**
- Column selector (filtered to date types)
- Operation type dropdown
- Dynamic parameter inputs
- Result column name
- Help text with examples

---

### 9. StringMethodsConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/StringMethodsConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Source column selector (string columns only)
- [ ] Method selector dropdown (uppercase, lowercase, title, capitalize, strip, etc.)
- [ ] Dynamic parameters based on method:
  - Slice: start/end indices
  - Replace: pattern + replacement
  - Extract: regex pattern + group
  - Padding: width + fill character
  - Split: delimiter + index
- [ ] New column name input (or overwrite option)
- [ ] Preview example transformation
- [ ] Save/Cancel handlers

**UI Elements:**
- Column selector (filtered to string types)
- Method dropdown (15+ methods)
- Dynamic parameter inputs
- Result column name
- Help text with regex examples

---

### 10. FillNullConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/FillNullConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Strategy selector (literal, forward, backward, mean, median, drop)
- [ ] Column selector (all columns or specific columns)
- [ ] Dynamic parameters based on strategy:
  - Literal: value input (type-aware)
  - Mean/Median: auto-calculate or manual
  - Drop: axis selector (rows/columns), threshold
- [ ] Preview null counts before/after
- [ ] Save/Cancel handlers

**UI Elements:**
- Strategy dropdown
- Column selector (multi-select)
- Dynamic parameter inputs
- Null count preview
- Help text with strategy explanations

---

### 11. DeduplicateConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/DeduplicateConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Column subset selector (all columns or specific)
- [ ] Keep strategy (first, last, none)
- [ ] Optional: show duplicate count preview
- [ ] Save/Cancel handlers

**UI Elements:**
- Column selector (multi-select, default all)
- Keep strategy radio buttons
- Duplicate count preview
- Help text with examples

---

### 12. ExplodeConfig Component (0% Complete)

**File:** `frontend/src/lib/components/operations/ExplodeConfig.svelte`

**Tasks:**
- [ ] Create Svelte 5 component with `$state()` runes
- [ ] Column selector (list/array columns only, multi-select)
- [ ] Handle null values checkbox
- [ ] Handle empty lists checkbox
- [ ] Preview row count before/after estimate
- [ ] Save/Cancel handlers

**UI Elements:**
- Column selector (filtered to list types)
- Null/empty handling options
- Row count preview
- Help text with examples

---

## Integration Tasks (0% Complete)

### 13. Update Operations Index (0% Complete)

**File:** `frontend/src/lib/components/operations/index.ts`

**Tasks:**
- [ ] Export `PivotConfig`
- [ ] Export `TimeSeriesConfig`
- [ ] Export `StringMethodsConfig`
- [ ] Export `FillNullConfig`
- [ ] Export `DeduplicateConfig`
- [ ] Export `ExplodeConfig`

---

### 14. Update StepLibrary (0% Complete)

**File:** `frontend/src/lib/components/pipeline/StepLibrary.svelte`

**Tasks:**
- [ ] Add "Advanced" category section
- [ ] Add Pivot operation card
- [ ] Add Time Series operation card
- [ ] Add String Methods operation card
- [ ] Add Fill Null operation card
- [ ] Add Deduplicate operation card
- [ ] Add Explode operation card
- [ ] Add icons/descriptions for each

---

### 15. Update Schema Calculator (0% Complete)

**File:** `frontend/src/lib/utils/schema/transformation-rules.ts`

**Tasks:**
- [ ] Add schema transformation for `pivot` (columns change dynamically)
- [ ] Add schema transformation for `timeseries` (add new columns with Int64/Date types)
- [ ] Add schema transformation for `string_transform` (preserve String type)
- [ ] Add schema transformation for `fill_null` (preserve types)
- [ ] Add schema transformation for `deduplicate` (preserve schema)
- [ ] Add schema transformation for `explode` (preserve schema, note row count change)

**Schema Calculation Logic:**
- **Pivot:** Dynamic - depends on unique values in pivot column
- **Time Series:** Add new column with appropriate date/int type
- **String Methods:** Add/modify column as String type
- **Fill Null:** No schema change
- **Deduplicate:** No schema change
- **Explode:** No schema change (but row count increases)

---

## Testing (0% Complete)

### 16. Backend Tests (0% Complete)

**File:** `backend/tests/test_advanced_operations.py`

**Tasks:**
- [ ] Test pivot with single aggregation
- [ ] Test pivot with multiple values per cell
- [ ] Test time series extraction (year, month, day)
- [ ] Test time series arithmetic (add/subtract days)
- [ ] Test string transformations (uppercase, lowercase, replace)
- [ ] Test string extraction with regex
- [ ] Test fill null with literal value
- [ ] Test fill null with forward/backward fill
- [ ] Test deduplicate with all columns
- [ ] Test deduplicate with subset
- [ ] Test explode with single column
- [ ] Test explode with multiple columns
- [ ] Test error handling for invalid inputs

**Expected Tests:** ~25-30 tests

---

### 17. Frontend Component Tests (0% Complete)

**Files:** `frontend/tests/[Component].test.ts`

**Tasks:**
- [ ] Test PivotConfig rendering and interaction
- [ ] Test TimeSeriesConfig operation switching
- [ ] Test StringMethodsConfig method selection
- [ ] Test FillNullConfig strategy changes
- [ ] Test DeduplicateConfig column selection
- [ ] Test ExplodeConfig column filtering
- [ ] Test all save/cancel handlers
- [ ] Test validation for required fields

**Expected Tests:** ~20-25 tests (pending @testing-library/svelte@6)

---

## Documentation (0% Complete)

### 18. Update User Documentation (0% Complete)

**Tasks:**
- [ ] Add examples for each new operation
- [ ] Document use cases
- [ ] Add troubleshooting guide
- [ ] Update operation comparison table

---

## Implementation Order Recommendation

1. **Phase 1 - Simple Operations (Start Here)**
   - Deduplicate (simplest)
   - Fill Null (straightforward)
   - String Methods (well-defined)

2. **Phase 2 - Moderate Complexity**
   - Time Series (requires type handling)
   - Explode (row multiplication)

3. **Phase 3 - Complex Operations**
   - Pivot (dynamic schema changes)

---

## Success Criteria

- [ ] All 6 backend operations working with test data
- [ ] All 6 frontend components rendering correctly
- [ ] Schema calculator updated for all operations
- [ ] StepLibrary shows all new operations
- [ ] All operations exported and available in editor
- [ ] Backend tests passing (25+ tests)
- [ ] Frontend components tested (pending library update)
- [ ] End-to-end manual test of each operation

---

## Notes

- **Pivot Complexity:** Pivot operation creates dynamic columns based on data values. Schema calculation will need special handling.
- **Time Series Types:** Polars has specific date/time types (Date, Datetime, Duration). Type handling is critical.
- **String Regex:** Frontend needs regex validation to prevent backend errors
- **Fill Null Strategy:** Mean/median only work on numeric columns - need type checking
- **Explode Row Count:** Explode can dramatically increase row count - consider adding warning in UI
- **Schema Calculator Limitations:** Some operations (like pivot) cannot calculate schema without data - may need to mark as "dynamic"

---

## Related Files

**Backend:**
- `backend/modules/compute/engine.py` - All operation implementations
- `backend/tests/test_advanced_operations.py` - New test file

**Frontend:**
- `frontend/src/lib/components/operations/*.svelte` - 6 new components
- `frontend/src/lib/components/operations/index.ts` - Exports
- `frontend/src/lib/components/pipeline/StepLibrary.svelte` - Operation palette
- `frontend/src/lib/utils/schema/transformation-rules.ts` - Schema logic
- `frontend/tests/*.test.ts` - Component tests

---

**Last Updated:** 2026-01-16
**Status:** Not started - all tasks pending
**Priority:** High - extends platform capabilities significantly

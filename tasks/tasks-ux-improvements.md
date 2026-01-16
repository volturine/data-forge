# UX Improvements - Empty States & Sample Datasets

**Overall Completion: 0%**

This task file tracks UX improvements including empty state handling for the analysis gallery and sample dataset functionality to help users get started quickly.

---

## Empty Gallery State (0% Complete)

### 1. Frontend: Empty Gallery Component (0% Complete)

**Purpose:** Provide helpful empty state when user has no analyses

**Location:** `frontend/src/lib/components/gallery/EmptyGalleryState.svelte`

**Tasks:**
- [ ] Create EmptyGalleryState component with Svelte 5 runes
- [ ] Add friendly illustration or icon
- [ ] Show welcome message for new users
- [ ] Add "Create Your First Analysis" CTA button
- [ ] Add "Load Sample Dataset" button
- [ ] Add quick tips about the platform
- [ ] Style with consistent design system

**UI Elements:**
- Icon/illustration (empty folder or data visualization)
- Heading: "No Analyses Yet"
- Subheading: "Get started by creating your first analysis or loading a sample dataset"
- Primary button: "Create Analysis" → links to `/analysis/new`
- Secondary button: "Browse Sample Datasets" → links to `/datasources/samples`
- Tips section with 3-4 bullet points

**Example Design:**
```
┌─────────────────────────────────────┐
│          📊 [Empty Icon]             │
│                                      │
│       No Analyses Yet                │
│                                      │
│  Get started by creating your first  │
│  analysis or exploring sample data   │
│                                      │
│  [Create Analysis] [Sample Datasets] │
│                                      │
│  Quick Tips:                         │
│  • Upload CSV, Parquet, or JSON      │
│  • Build pipelines visually          │
│  • Export results in multiple formats│
└─────────────────────────────────────┘
```

---

### 2. Frontend: Update Gallery Page (0% Complete)

**File:** `frontend/src/routes/+page.svelte`

**Tasks:**
- [ ] Import EmptyGalleryState component
- [ ] Add conditional rendering: show EmptyGalleryState when analyses.length === 0
- [ ] Show GalleryGrid when analyses.length > 0
- [ ] Add loading state handling
- [ ] Add error state handling

**Implementation:**
```svelte
{#if isLoading}
  <LoadingSpinner />
{:else if error}
  <ErrorMessage error={error} />
{:else if analyses.length === 0}
  <EmptyGalleryState />
{:else}
  <GalleryGrid analyses={analyses} />
{/if}
```

---

## Sample Datasets Feature (0% Complete)

### 3. Backend: Sample Datasets Module (0% Complete)

**Purpose:** Provide curated sample datasets for users to explore

**Location:** `backend/modules/samples/`

**Tasks:**
- [ ] Create `backend/modules/samples/` directory
- [ ] Create `models.py` (SampleDataset model)
- [ ] Create `schemas.py` (SampleDatasetResponse)
- [ ] Create `service.py` (list samples, load sample)
- [ ] Create `routes.py` (API endpoints)
- [ ] Add sample data files to `backend/data/samples/`

**Database Model:**
```python
class SampleDataset(Base):
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)  # Sales, HR, Financial, etc.
    file_path: Mapped[str] = mapped_column(String)
    file_type: Mapped[str] = mapped_column(String)  # csv, parquet, json
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    tags: Mapped[str] = mapped_column(String)  # JSON array
```

**API Endpoints:**
- `GET /api/samples` - List all sample datasets
- `GET /api/samples/{id}` - Get sample details
- `POST /api/samples/{id}/load` - Load sample as datasource

---

### 4. Backend: Sample Data Files (0% Complete)

**Location:** `backend/data/samples/`

**Tasks:**
- [ ] Create directory `backend/data/samples/`
- [ ] Add `sales_data.csv` (500 rows, 8 columns)
- [ ] Add `employee_data.csv` (200 rows, 10 columns)
- [ ] Add `financial_transactions.csv` (1000 rows, 7 columns)
- [ ] Add `customer_orders.json` (300 rows, 12 columns)
- [ ] Add `product_inventory.parquet` (150 rows, 9 columns)
- [ ] Add `time_series_metrics.csv` (2000 rows, 5 columns)
- [ ] Create `README.md` with dataset descriptions

**Sample Dataset: sales_data.csv**
Columns:
- date (Date)
- product_id (String)
- product_name (String)
- category (String)
- quantity (Int)
- price (Float)
- revenue (Float)
- region (String)

**Sample Dataset: employee_data.csv**
Columns:
- employee_id (String)
- first_name (String)
- last_name (String)
- email (String)
- department (String)
- position (String)
- salary (Float)
- hire_date (Date)
- manager_id (String)
- location (String)

**Sample Dataset: financial_transactions.csv**
Columns:
- transaction_id (String)
- date (Date)
- account_id (String)
- type (String) - debit/credit
- amount (Float)
- balance (Float)
- description (String)

---

### 5. Backend: Sample Service Implementation (0% Complete)

**File:** `backend/modules/samples/service.py`

**Tasks:**
- [ ] Implement `list_samples()` - return all sample datasets
- [ ] Implement `get_sample(sample_id)` - get sample details
- [ ] Implement `load_sample(sample_id, user_id)` - copy sample to user datasources
- [ ] Add schema extraction for samples
- [ ] Add thumbnail generation
- [ ] Handle file copying to user uploads directory
- [ ] Create DataSource record when sample is loaded

**Key Functions:**
```python
async def list_samples() -> list[SampleDatasetResponse]:
    """List all available sample datasets."""
    pass

async def get_sample(sample_id: str) -> SampleDatasetResponse:
    """Get details of a specific sample dataset."""
    pass

async def load_sample(sample_id: str, db: AsyncSession) -> DataSourceResponse:
    """Load sample dataset as a new datasource."""
    # 1. Copy sample file to uploads directory
    # 2. Extract schema using Polars
    # 3. Create DataSource record
    # 4. Return DataSourceResponse
    pass
```

---

### 6. Frontend: Sample Datasets Page (0% Complete)

**File:** `frontend/src/routes/datasources/samples/+page.svelte`

**Tasks:**
- [ ] Create samples page route
- [ ] Create SampleDatasetCard component
- [ ] Display grid of sample datasets
- [ ] Show dataset name, description, category
- [ ] Show row/column count and file size
- [ ] Add "Load Dataset" button on each card
- [ ] Add category filter (All, Sales, HR, Financial, etc.)
- [ ] Add search functionality
- [ ] Handle loading state
- [ ] Show success message after loading
- [ ] Redirect to analysis creation after loading

**UI Layout:**
```
┌─────────────────────────────────────────┐
│  Sample Datasets                        │
│  ───────────────                        │
│                                         │
│  [Search...] [Category: All ▼]         │
│                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │ 📊 Sales │ │ 👥 HR    │ │ 💰 Finance││
│  │ Data     │ │ Data     │ │ Data     ││
│  │          │ │          │ │          ││
│  │ 500 rows │ │ 200 rows │ │ 1K rows  ││
│  │ 8 cols   │ │ 10 cols  │ │ 7 cols   ││
│  │          │ │          │ │          ││
│  │ [Load]   │ │ [Load]   │ │ [Load]   ││
│  └──────────┘ └──────────┘ └──────────┘│
└─────────────────────────────────────────┘
```

---

### 7. Frontend: Sample API Client (0% Complete)

**File:** `frontend/src/lib/api/samples.ts`

**Tasks:**
- [ ] Create `listSamples()` function
- [ ] Create `getSample(id)` function
- [ ] Create `loadSample(id)` function
- [ ] Add TypeScript types
- [ ] Add error handling
- [ ] Export all functions

**Implementation:**
```typescript
export async function listSamples(): Promise<SampleDataset[]> {
  return apiRequest('/api/samples');
}

export async function loadSample(id: string): Promise<DataSource> {
  return apiRequest(`/api/samples/${id}/load`, { method: 'POST' });
}
```

---

### 8. Frontend: Sample Dataset Card Component (0% Complete)

**File:** `frontend/src/lib/components/samples/SampleDatasetCard.svelte`

**Tasks:**
- [ ] Create component with Svelte 5 runes
- [ ] Display dataset icon based on category
- [ ] Show name, description, category badge
- [ ] Show statistics (rows, columns, size)
- [ ] Show tags as chips
- [ ] Add "Load Dataset" button
- [ ] Add loading state during load
- [ ] Add preview modal (optional)

**Props:**
```typescript
interface Props {
  sample: SampleDataset;
  onLoad: (id: string) => Promise<void>;
}
```

---

## Integration Tasks (0% Complete)

### 9. Update Main Routes (0% Complete)

**Files to Update:**
- `backend/main.py` - Add samples router
- `frontend/src/lib/components/gallery/index.ts` - Export EmptyGalleryState
- `frontend/src/routes/datasources/+page.svelte` - Add "Browse Samples" button

**Tasks:**
- [ ] Register samples router in FastAPI
- [ ] Add navigation link to samples page
- [ ] Update datasources page with samples link
- [ ] Update empty gallery CTA to link to samples

---

### 10. Sample Data Generation Script (0% Complete)

**File:** `backend/scripts/generate_samples.py`

**Tasks:**
- [ ] Create script to generate sample datasets
- [ ] Use Faker library for realistic data
- [ ] Generate sales_data.csv
- [ ] Generate employee_data.csv
- [ ] Generate financial_transactions.csv
- [ ] Generate customer_orders.json
- [ ] Generate product_inventory.parquet
- [ ] Generate time_series_metrics.csv
- [ ] Add script to project scripts

**Usage:**
```bash
cd backend
uv run python scripts/generate_samples.py
```

---

### 11. Database Migration for Samples (0% Complete)

**File:** `backend/database/alembic/versions/xxx_add_sample_datasets.py`

**Tasks:**
- [ ] Create migration for sample_datasets table
- [ ] Add indexes on category and tags
- [ ] Seed initial sample dataset records
- [ ] Test upgrade/downgrade

---

## Testing (0% Complete)

### 12. Backend Tests (0% Complete)

**File:** `backend/tests/test_samples.py`

**Tasks:**
- [ ] Test list_samples endpoint
- [ ] Test get_sample endpoint
- [ ] Test load_sample endpoint
- [ ] Test loading non-existent sample (404)
- [ ] Test sample schema extraction
- [ ] Test file copying during load

**Expected Tests:** ~10-15 tests

---

### 13. Frontend Tests (0% Complete)

**Files:**
- `frontend/tests/EmptyGalleryState.test.ts`
- `frontend/tests/SampleDatasetCard.test.ts`

**Tasks:**
- [ ] Test EmptyGalleryState rendering
- [ ] Test CTA button clicks
- [ ] Test SampleDatasetCard rendering
- [ ] Test load button functionality
- [ ] Test category filtering
- [ ] Test search functionality

**Expected Tests:** ~8-12 tests

---

## Path Selection Feature (0% Complete)

### 14. Frontend: File Path Input Component (0% Complete)

**Purpose:** Allow users to specify file paths instead of uploading

**File:** `frontend/src/lib/components/datasource/FilePathInput.svelte`

**Tasks:**
- [ ] Create component with Svelte 5 runes
- [ ] Add text input for file path
- [ ] Add file type dropdown (auto-detect from extension)
- [ ] Add "Browse" button (if running locally)
- [ ] Add validation for path format
- [ ] Add preview of detected schema
- [ ] Show error if path doesn't exist

**UI:**
```
┌─────────────────────────────────────┐
│ File Path Input                     │
│                                     │
│ [/path/to/data.csv            ]    │
│                                     │
│ File Type: [CSV ▼]                 │
│                                     │
│ ✓ File detected: 1,234 rows        │
│                                     │
│ [Load Dataset]                      │
└─────────────────────────────────────┘
```

---

### 15. Frontend: Update Datasource Upload Page (0% Complete)

**File:** `frontend/src/routes/datasources/new/+page.svelte`

**Tasks:**
- [ ] Add tab switcher: "Upload File" vs "File Path"
- [ ] Show file upload UI in "Upload File" tab
- [ ] Show FilePathInput in "File Path" tab
- [ ] Handle both upload and path-based creation
- [ ] Update API calls to support path parameter

**UI:**
```
┌────────────────────────────────────┐
│ [Upload File] [File Path]          │
│                                    │
│ (Tab content based on selection)   │
└────────────────────────────────────┘
```

---

### 16. Backend: Support File Path Datasources (0% Complete)

**File:** `backend/modules/datasource/service.py`

**Tasks:**
- [ ] Update `create_datasource()` to accept file_path parameter
- [ ] Skip file upload if file_path provided
- [ ] Validate file_path exists and is readable
- [ ] Extract schema from file_path
- [ ] Support absolute and relative paths
- [ ] Add security check (prevent path traversal)

**Schema Update:**
```python
class DataSourceCreate(BaseModel):
    name: str
    source_type: str = 'file'
    file_type: str
    file_path: str | None = None  # New field
    # file upload handled separately
```

---

## Documentation (0% Complete)

### 17. Update User Guide (0% Complete)

**Tasks:**
- [ ] Document empty gallery state
- [ ] Document sample datasets feature
- [ ] Add screenshots of empty state
- [ ] Add guide for loading samples
- [ ] Document file path input feature
- [ ] Add examples of valid file paths

---

## Success Criteria

- [ ] Empty gallery shows helpful state with CTAs
- [ ] Users can browse 6+ sample datasets
- [ ] Samples load successfully into datasources
- [ ] Sample datasets have realistic, useful data
- [ ] Users can input file paths directly
- [ ] File path validation works correctly
- [ ] All tests passing
- [ ] UI is polished and user-friendly

---

## Implementation Order

**Phase 1 - Empty State (Quick Win)**
1. EmptyGalleryState component
2. Update gallery page

**Phase 2 - Sample Datasets (Core Feature)**
1. Generate sample data files
2. Backend samples module
3. Sample datasets page
4. Sample API integration

**Phase 3 - File Path Input (Enhancement)**
1. FilePathInput component
2. Update datasource creation
3. Backend path support

---

## Notes

- **Sample Data Quality:** Use realistic, interesting data that demonstrates platform capabilities
- **Security:** File path feature needs strict validation to prevent path traversal attacks
- **Performance:** Sample datasets should be reasonably sized (not too large)
- **Categories:** Group samples by domain (Sales, HR, Finance, Marketing, etc.)
- **Discoverability:** Make empty state and samples very visible to new users

---

## Related Files

**Backend:**
- `backend/modules/samples/` - New module
- `backend/data/samples/` - Sample data files
- `backend/modules/datasource/service.py` - Update for path support
- `backend/scripts/generate_samples.py` - Data generation

**Frontend:**
- `frontend/src/lib/components/gallery/EmptyGalleryState.svelte` - New
- `frontend/src/lib/components/samples/` - New directory
- `frontend/src/routes/datasources/samples/+page.svelte` - New
- `frontend/src/lib/api/samples.ts` - New

---

**Last Updated:** 2026-01-16
**Status:** Not started - all tasks pending
**Priority:** High - improves first-time user experience significantly

# PRD: Hugging Face Connection

## Overview

Integrate Hugging Face as a first-class model and dataset hub in Data-Forge, enabling users to pull pre-trained models from the Hugging Face Model Hub, load them onto GPU for inference, and optionally ingest Hugging Face datasets as datasources.

## Problem Statement

Data-Forge currently supports AI operations (per-row LLM transformations) via Ollama and OpenAI APIs, but users cannot browse, select, or download models from the Hugging Face ecosystem — the largest open-source model hub with 500,000+ models. Users who want to use specialized models (e.g., fine-tuned classifiers, NER models, embedding models) must manually download and configure them outside the platform.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Browse and search Hugging Face models from within Data-Forge | Users can discover models without leaving the app |
| G-2 | Pull models to local storage and load onto GPU | Model available for inference within pipeline steps |
| G-3 | Use HF models as a provider for AI operations and chat | HF models selectable in AI step config and chat settings |
| G-4 | Track model provenance and versions | Model metadata (repo, revision, size) recorded |
| G-5 | Support Hugging Face Inference API (remote) | Users can call hosted models without local GPU |
| G-6 | Ingest Hugging Face datasets as datasources | Users can browse, search, and import HF datasets directly into Data-Forge |

## Non-Goals

- Fine-tuning or training models within Data-Forge
- Publishing models to Hugging Face
- Hugging Face Spaces integration

## User Stories

### US-1: Authenticate with Hugging Face

> As a user, I want to enter my Hugging Face API token so that I can access models and the Inference API.

**Acceptance Criteria:**

1. Settings page has a "Hugging Face" section with a `hf_api_token` field.
2. Token stored encrypted in `AppSettings`.
3. "Test Connection" button validates token against HF API.
4. Token persists across sessions.

### US-2: Browse and Search Models

> As a user, I want to search Hugging Face models by task type, name, or keyword, and see model metadata before pulling.

**Acceptance Criteria:**

1. New "Model Hub" page or section accessible from navigation.
2. Search with filters: task (text-generation, text-classification, token-classification, etc.), library (transformers, gguf, etc.), sort (downloads, trending, recently updated).
3. Results show: model name, author, downloads, likes, task tags, model size, last modified.
4. Detail view shows: model card summary, supported tasks, files listing with sizes, hardware requirements.

### US-3: Pull Model to Local Storage

> As a user, I want to download a model from Hugging Face to my local machine so I can use it for offline inference.

**Acceptance Criteria:**

1. "Pull Model" action on model detail view.
2. Configurable storage path (default: `DATA_DIR/models/<model_repo>/`).
3. Progress indicator showing download percentage, speed, and ETA.
4. Support for pulling specific revisions/branches (main, specific commit).
5. Model registry tracks pulled models with status (downloading, ready, error).
6. Resume interrupted downloads.

### US-4: Load Model onto GPU

> As a user, I want to load a pulled model onto my GPU so it can serve inference requests for pipeline steps.

**Acceptance Criteria:**

1. "Load Model" action on pulled models in the model registry.
2. GPU selection (if multiple GPUs available).
3. Quantization options: none, 4-bit, 8-bit (for supported model types).
4. Memory estimation shown before loading (estimated VRAM usage).
5. Model status: unloaded → loading → ready → error.
6. Graceful unloading when switching models.

### US-5: Use HF Model in AI Pipeline Step

> As a user, I want to select a loaded HF model as the provider for an AI operation step in my pipeline.

**Acceptance Criteria:**

1. AI step config dropdown includes "huggingface-local" provider option (for loaded models).
2. AI step config dropdown includes "huggingface-api" provider option (for Inference API).
3. Local: model selection shows only loaded/ready models.
4. Remote: model name input with autocomplete from HF search.
5. Task-specific configuration (e.g., text-generation: max_tokens, temperature; classification: return labels).

### US-6: Use HF Inference API (Remote)

> As a user, I want to use Hugging Face's hosted Inference API for models I don't want to run locally.

**Acceptance Criteria:**

1. "huggingface-api" provider option in AI step config and chat settings.
2. Model selector searches HF models with Inference API support.
3. Automatic rate limiting and retry logic.
4. Cost awareness: show if model is free-tier or paid.

### US-7: Browse and Search Hugging Face Datasets

> As a user, I want to search Hugging Face datasets by keyword, task, or size and preview metadata before importing.

**Acceptance Criteria:**

1. "Hugging Face" tab in the datasource creation flow (`/datasources/new`) alongside existing options.
2. Search with filters: task (e.g., text-classification, question-answering), size category, sort (downloads, trending, recently updated).
3. Results show: dataset name, author, downloads, size, task tags, last modified.
4. Detail view shows: dataset card summary, available splits (train/test/validation), column schema, sample rows.

### US-8: Ingest Hugging Face Dataset as Datasource

> As a user, I want to import a Hugging Face dataset (or a specific split) as a Data-Forge datasource.

**Acceptance Criteria:**

1. After selecting a dataset, user sees available splits and configurations.
2. User can select which split(s) to import (each becomes a separate datasource).
3. Import triggers background download via HF Hub API → saved to `DATA_DIR/uploads/<namespace>/`.
4. Datasource created with `source_type: 'huggingface'` and metadata containing `hf_dataset_ref`, `hf_split`, `hf_revision`.
5. Progress indicator during download.
6. On completion, datasource appears in datasource list with schema auto-detected.

## Technical Design

### Backend

#### New Module: `backend/modules/huggingface/`

```
modules/huggingface/
├── __init__.py
├── routes.py        # API endpoints
├── service.py       # HF Hub client and model management
├── inference.py     # Inference server (local model serving)
├── schemas.py       # Pydantic request/response models
└── models.py        # DB model for model registry
```

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/huggingface/test` | Test HF token |
| `GET` | `/api/v1/huggingface/models` | Search models (query, task, library, sort, page) |
| `GET` | `/api/v1/huggingface/models/{repo_id}` | Get model metadata |
| `POST` | `/api/v1/huggingface/models/pull` | Start model download |
| `GET` | `/api/v1/huggingface/models/pull/{job_id}/status` | Poll download progress |
| `GET` | `/api/v1/huggingface/registry` | List pulled models |
| `POST` | `/api/v1/huggingface/registry/{model_id}/load` | Load model onto GPU |
| `POST` | `/api/v1/huggingface/registry/{model_id}/unload` | Unload model from GPU |
| `DELETE` | `/api/v1/huggingface/registry/{model_id}` | Delete pulled model |
| `POST` | `/api/v1/huggingface/inference` | Run inference (local or remote) |
| `GET` | `/api/v1/huggingface/datasets` | Search datasets (query, task, sort, page) |
| `GET` | `/api/v1/huggingface/datasets/{repo_id}` | Get dataset metadata, splits, schema |
| `POST` | `/api/v1/huggingface/datasets/ingest` | Download and register dataset split as datasource |
| `GET` | `/api/v1/huggingface/datasets/ingest/{job_id}/status` | Poll dataset ingest progress |

#### HF API Integration

- Use Hugging Face Hub API (`https://huggingface.co/api/`) via `httpx.AsyncClient`.
- Key endpoints consumed:
  - `GET /api/models` — search and list models
  - `GET /api/models/{repo_id}` — model card, files, metadata
  - `GET /api/models/{repo_id}/tree/{revision}` — file listing
  - Download via `hf_hub_url()` pattern for individual files
- For Inference API: `POST https://api-inference.huggingface.co/models/{model_id}`

#### Model Registry (DB)

```python
class ModelRegistry(SQLModel, table=True):
    id: str  # UUID
    repo_id: str  # e.g., "meta-llama/Llama-2-7b-chat-hf"
    revision: str  # git commit or branch
    task: str  # e.g., "text-generation"
    library: str  # e.g., "transformers", "gguf"
    local_path: str  # path on disk
    size_bytes: int
    status: str  # "downloading" | "ready" | "loading" | "loaded" | "error"
    gpu_device: str | None  # e.g., "cuda:0"
    quantization: str | None  # "4bit" | "8bit" | None
    pulled_at: datetime
    loaded_at: datetime | None
    metadata: dict  # additional model card info
```

#### Model Loading Architecture

```
ModelManager (singleton)
├─ pull_model(repo_id, revision)
│  ├─ Download files to DATA_DIR/models/{repo_id}/
│  ├─ Track progress via background task
│  └─ Update ModelRegistry status
├─ load_model(model_id, device, quantization)
│  ├─ Load model + tokenizer into memory
│  ├─ Optionally apply quantization (bitsandbytes)
│  ├─ Register as inference endpoint
│  └─ Update ModelRegistry status
├─ unload_model(model_id)
│  ├─ Free GPU memory
│  └─ Update status → "ready"
├─ inference(model_id, inputs, task_params)
│  ├─ Route to loaded local model or HF Inference API
│  └─ Return structured output
└─ list_loaded_models() → [ModelInfo]
```

#### Integration with Existing AI Operation

Extend `AIParams` in `backend/modules/compute/operations/ai.py`:

```python
class AIParams(OperationParams):
    provider: Literal['ollama', 'openai', 'huggingface-local', 'huggingface-api'] = 'ollama'
    # ... existing fields ...
    hf_model_id: str | None = None  # For registry reference (local)
    hf_repo_id: str | None = None   # For Inference API (remote)
    hf_task: str | None = None      # text-generation, text-classification, etc.
```

### Frontend

#### Settings Integration

- Add Hugging Face section to Settings page.
- Field: `hf_api_token` (password with show/hide toggle).
- "Test Connection" button.

#### Model Hub Page

- New route: `/models` (or `/models/hub`).
- Search bar + filter dropdowns (task, library, sort).
- Model cards in grid or list layout.
- Detail modal with model card content, files, pull action.

#### Model Registry Panel

- Route: `/models/local` (or tab within Model Hub).
- Table: model name, status, size, GPU assignment, actions.
- Actions: Load, Unload, Delete.
- Status indicators: downloading (progress bar), ready (green), loaded (blue), error (red).

#### AI Step Config Update

- Provider dropdown extended with "Hugging Face (Local)" and "Hugging Face (API)".
- Conditional fields based on provider selection.
- Model picker that searches loaded models (local) or HF Hub (API).

### Data Model Changes

Extend `AppSettings`:

```python
hf_api_token: str = ""
```

New `model_registry` table (see Model Registry DB section above).

### Dependencies

| Package | Version | Ecosystem | Purpose |
|---------|---------|-----------|---------|
| `huggingface-hub` | `>=0.20.0` | pip | Model download and HF API client |

The `huggingface-hub` package provides robust download resumption, progress tracking, and API wrappers. Model loading/inference would use PyTorch/transformers, but these are optional dependencies gated behind the model loading feature.

### Security Considerations

- HF API token stored encrypted at rest.
- Token never exposed in frontend responses.
- Downloaded models validated against expected checksums (provided by HF Hub).
- Model loading sandboxed: models loaded in separate process (similar to compute engine isolation).
- GPU memory limits enforced to prevent OOM crashes.

## Migration

- Alembic migration to add `hf_api_token` to `app_settings`.
- Alembic migration to create `model_registry` table.
- No data migration needed — new features are additive.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: HF API client, settings, search endpoints | 2 days |
| 2 | Backend: Model pull, registry, progress tracking | 3 days |
| 3 | Backend: Model loading, inference serving | 4 days |
| 4 | Backend: Integration with AI operation step | 2 days |
| 5 | Frontend: Settings, Model Hub page, registry panel | 3 days |
| 6 | Frontend: AI step config updates | 2 days |
| 7 | Testing, GPU edge cases, memory management | 3 days |

## Open Questions

1. Should model loading use a separate process (like compute engines) or share the main process? Separate process is safer for GPU memory management.
2. Do we need support for GGUF/llama.cpp models (popular for local inference) in addition to transformers?
3. Should we support model caching across users/workspaces, or per-workspace isolation?
4. What is the minimum GPU VRAM threshold to enable the "Load Model" feature?

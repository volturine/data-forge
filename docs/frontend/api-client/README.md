# API Client

Documentation for the HTTP client layer connecting to the FastAPI backend.

## Overview

The API client uses the Fetch API with type-safe wrappers. It supports both Result-based error handling (neverthrow) and traditional Promise-based calls.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        API Client Layer                              │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ analysis.ts │  │datasource.ts│  │ compute.ts  │  │  health.ts  │ │
│  │             │  │             │  │             │  │             │ │
│  │ -getAnalysis│  │ -list       │  │ -execute    │  │ -check      │ │
│  │ -create     │  │ -upload     │  │ -getStatus  │  │             │ │
│  │ -update     │  │ -delete     │  │ -getResult  │  │             │ │
│  │ -delete     │  │             │  │             │  │             │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         │                │                │                │        │
│         └────────────────┼────────────────┼────────────────┘        │
│                          │                │                          │
│                          ▼                ▼                          │
│                    ┌─────────────────────────────┐                   │
│                    │         client.ts           │                   │
│                    │                             │                   │
│                    │  - apiRequest<T>()          │                   │
│                    │  - apiRequestSafe<T>()      │                   │
│                    │  - BASE_URL                 │                   │
│                    └─────────────────────────────┘                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Base Client

### Configuration

```typescript
// lib/api/client.ts

// Dev: Use Vite proxy (empty base)
// Prod: Use VITE_API_URL or runtime detection
const apiEnv = import.meta.env.VITE_API_URL?.trim();

const runtimeBase =
    typeof window === 'undefined'
        ? 'http://localhost:8000'
        : `${window.location.protocol}//${window.location.hostname}:8000`;

export const BASE_URL = import.meta.env.DEV ? '' : apiEnv || runtimeBase;
```

### Error Types

```typescript
export type ApiErrorType = 'network' | 'http' | 'parse';

export interface ApiError {
    type: ApiErrorType;
    message: string;
    status?: number;
    statusText?: string;
}
```

### Safe Request (Result-based)

```typescript
import { ResultAsync } from 'neverthrow';

export function apiRequestSafe<T>(
    endpoint: string,
    options?: RequestInit
): ResultAsync<T, ApiError> {
    return ResultAsync.fromPromise(
        fetch(`${BASE_URL}${endpoint}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options?.headers
            }
        }),
        (error): ApiError => ({
            type: 'network',
            message: error instanceof Error ? error.message : 'Network error'
        })
    ).andThen((response) => {
        if (!response.ok) {
            return ResultAsync.fromPromise(
                response.text(),
                () => ({ type: 'http', message: response.statusText })
            ).andThen((errorText) =>
                err({
                    type: 'http',
                    message: errorText || response.statusText,
                    status: response.status
                })
            );
        }
        return ResultAsync.fromPromise(
            response.json() as Promise<T>,
            (): ApiError => ({ type: 'parse', message: 'Failed to parse JSON' })
        );
    });
}
```

**Usage**:

```typescript
const result = await apiRequestSafe<Analysis>('/api/v1/analysis/123');

if (result.isOk()) {
    console.log(result.value);  // Analysis
} else {
    console.error(result.error);  // ApiError
}
```

### Legacy Request (throws)

```typescript
export async function apiRequest<T>(
    endpoint: string,
    options?: RequestInit
): Promise<T> {
    const result = await apiRequestSafe<T>(endpoint, options);

    if (result.isErr()) {
        throw new Error(`${result.error.type} error: ${result.error.message}`);
    }

    return result.value;
}
```

## API Modules

### Analysis API

```typescript
// lib/api/analysis.ts
import { apiRequest } from './client';
import type { Analysis, AnalysisCreate, AnalysisUpdate } from '$lib/types/analysis';

export async function getAnalysis(id: string): Promise<Analysis> {
    return apiRequest<Analysis>(`/api/v1/analysis/${id}`);
}

export async function listAnalyses(): Promise<Analysis[]> {
    return apiRequest<Analysis[]>('/api/v1/analysis');
}

export async function createAnalysis(data: AnalysisCreate): Promise<Analysis> {
    return apiRequest<Analysis>('/api/v1/analysis', {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

export async function updateAnalysis(
    id: string,
    data: AnalysisUpdate
): Promise<Analysis> {
    return apiRequest<Analysis>(`/api/v1/analysis/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

export async function deleteAnalysis(id: string): Promise<void> {
    await apiRequest(`/api/v1/analysis/${id}`, {
        method: 'DELETE'
    });
}
```

### Datasource API

```typescript
// lib/api/datasource.ts
import { apiRequest, BASE_URL } from './client';
import type { DataSource } from '$lib/types/datasource';

export async function listDatasources(): Promise<DataSource[]> {
    return apiRequest<DataSource[]>('/api/v1/datasource');
}

export async function getDatasource(id: string): Promise<DataSource> {
    return apiRequest<DataSource>(`/api/v1/datasource/${id}`);
}

export async function uploadFile(
    file: File,
    name: string
): Promise<DataSource> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);

    const response = await fetch(`${BASE_URL}/api/v1/datasource/upload`, {
        method: 'POST',
        body: formData  // No Content-Type header for FormData
    });

    if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`);
    }

    return response.json();
}

export async function connectDatabase(
    name: string,
    connectionString: string,
    query: string
): Promise<DataSource> {
    return apiRequest<DataSource>('/api/v1/datasource/database', {
        method: 'POST',
        body: JSON.stringify({
            name,
            connection_string: connectionString,
            query
        })
    });
}

export async function deleteDatasource(id: string): Promise<void> {
    await apiRequest(`/api/v1/datasource/${id}`, {
        method: 'DELETE'
    });
}
```

### Compute API

```typescript
// lib/api/compute.ts
import { apiRequest } from './client';
import type { JobStatus, ComputeResult } from '$lib/types/compute';

export async function executeAnalysis(
    analysisId: string,
    tabId: string
): Promise<{ job_id: string }> {
    return apiRequest<{ job_id: string }>('/api/v1/compute/execute', {
        method: 'POST',
        body: JSON.stringify({
            analysis_id: analysisId,
            tab_id: tabId
        })
    });
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
    return apiRequest<JobStatus>(`/api/v1/compute/job/${jobId}`);
}

export async function getJobResult(jobId: string): Promise<ComputeResult> {
    return apiRequest<ComputeResult>(`/api/v1/compute/job/${jobId}/result`);
}
```

### Health API

```typescript
// lib/api/health.ts
import { apiRequest } from './client';

export interface HealthStatus {
    status: string;
    version: string;
}

export async function checkHealth(): Promise<HealthStatus> {
    return apiRequest<HealthStatus>('/api/v1/health');
}
```

## TanStack Query Integration

### Query Setup

```typescript
// lib/api/query.ts
import { QueryClient } from '@tanstack/svelte-query';

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60 * 1000,  // 5 minutes
            gcTime: 10 * 60 * 1000,    // 10 minutes
            retry: 1,
            refetchOnWindowFocus: false
        }
    }
});
```

### Using Queries

```svelte
<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { listAnalyses } from '$lib/api/analysis';

    const analysesQuery = createQuery({
        queryKey: ['analyses'],
        queryFn: listAnalyses
    });
</script>

{#if $analysesQuery.isLoading}
    <p>Loading...</p>
{:else if $analysesQuery.error}
    <p>Error: {$analysesQuery.error.message}</p>
{:else}
    <ul>
        {#each $analysesQuery.data ?? [] as analysis}
            <li>{analysis.name}</li>
        {/each}
    </ul>
{/if}
```

### Using Mutations

```svelte
<script lang="ts">
    import { createMutation, useQueryClient } from '@tanstack/svelte-query';
    import { createAnalysis } from '$lib/api/analysis';

    const queryClient = useQueryClient();

    const createMutation = createMutation({
        mutationFn: createAnalysis,
        onSuccess: () => {
            // Invalidate and refetch
            queryClient.invalidateQueries({ queryKey: ['analyses'] });
        }
    });

    async function handleCreate() {
        $createMutation.mutate({ name: 'New Analysis' });
    }
</script>

<button onclick={handleCreate} disabled={$createMutation.isPending}>
    {$createMutation.isPending ? 'Creating...' : 'Create'}
</button>
```

## Development Proxy

Vite proxies API requests in development:

```typescript
// vite.config.ts
export default defineConfig({
    server: {
        port: 3000,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true
            }
        }
    }
});
```

**Request flow**:
```
Browser → http://localhost:3000/api/v1/health
         ↓ (Vite proxy)
Backend → http://localhost:8000/api/v1/health
```

## Error Handling Patterns

### In Components

```svelte
<script lang="ts">
    import { getAnalysis } from '$lib/api/analysis';

    let error = $state<string | null>(null);
    let analysis = $state<Analysis | null>(null);

    async function load(id: string) {
        error = null;
        try {
            analysis = await getAnalysis(id);
        } catch (err) {
            error = err instanceof Error ? err.message : 'Unknown error';
        }
    }
</script>

{#if error}
    <div class="error">{error}</div>
{/if}
```

### With Result Type

```typescript
import { apiRequestSafe } from '$lib/api/client';

const result = await apiRequestSafe<Analysis>('/api/v1/analysis/123');

result.match(
    (analysis) => {
        // Handle success
        console.log('Got analysis:', analysis.name);
    },
    (error) => {
        // Handle error
        if (error.status === 404) {
            console.log('Analysis not found');
        } else {
            console.error('API error:', error.message);
        }
    }
);
```

## See Also

- [State Management](../state-management/README.md) - Store integration
- [API Endpoints](../../api/endpoints/README.md) - Backend API docs
- [Type Definitions](../../reference/type-definitions.md) - TypeScript type definitions

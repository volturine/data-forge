/**
 * Context-based store management for SSR safety and better testability.
 *
 * This module provides a centralized way to create and access stores via Svelte's context API,
 * preventing shared state between server requests and enabling easier testing.
 *
 * Usage:
 * 1. In root layout: call initializeStores() to create and set all stores
 * 2. In components: use getXxxContext() to access stores (falls back to singletons for backward compat)
 */

import { setContext, getContext, hasContext } from 'svelte';
import { AnalysisStore } from './analysis.svelte';
import { DatasourceStore } from './datasource.svelte';
import { SchemaStore } from './schema.svelte';
import { EnginesStore } from './engines.svelte';
import { ConfigStore } from './config.svelte';

// Import singletons for fallback (backward compatibility during migration)
import { analysisStore as analysisSingleton } from './analysis.svelte';
import { datasourceStore as datasourceSingleton } from './datasource.svelte';
import { schemaStore as schemaSingleton } from './schema.svelte';
import { enginesStore as enginesSingleton } from './engines.svelte';
import { configStore as configSingleton } from './config.svelte';

// Context keys (using Symbols for uniqueness)
const ANALYSIS_STORE_KEY = Symbol('analysis-store');
const DATASOURCE_STORE_KEY = Symbol('datasource-store');
const SCHEMA_STORE_KEY = Symbol('schema-store');
const ENGINES_STORE_KEY = Symbol('engines-store');
const CONFIG_STORE_KEY = Symbol('config-store');

// Store factory functions
export function createAnalysisStore(): AnalysisStore {
	return new AnalysisStore();
}

export function createDatasourceStore(): DatasourceStore {
	return new DatasourceStore();
}

export function createSchemaStore(): SchemaStore {
	return new SchemaStore();
}

export function createEnginesStore(): EnginesStore {
	return new EnginesStore();
}

export function createConfigStore(): ConfigStore {
	return new ConfigStore();
}

// Context setters (called in root layout)
export function setAnalysisContext(store: AnalysisStore): void {
	setContext(ANALYSIS_STORE_KEY, store);
}

export function setDatasourceContext(store: DatasourceStore): void {
	setContext(DATASOURCE_STORE_KEY, store);
}

export function setSchemaContext(store: SchemaStore): void {
	setContext(SCHEMA_STORE_KEY, store);
}

export function setEnginesContext(store: EnginesStore): void {
	setContext(ENGINES_STORE_KEY, store);
}

export function setConfigContext(store: ConfigStore): void {
	setContext(CONFIG_STORE_KEY, store);
}

// Context getters with fallback to singleton for backward compatibility
export function getAnalysisContext(): AnalysisStore {
	if (hasContext(ANALYSIS_STORE_KEY)) {
		return getContext<AnalysisStore>(ANALYSIS_STORE_KEY);
	}
	return analysisSingleton;
}

export function getDatasourceContext(): DatasourceStore {
	if (hasContext(DATASOURCE_STORE_KEY)) {
		return getContext<DatasourceStore>(DATASOURCE_STORE_KEY);
	}
	return datasourceSingleton;
}

export function getSchemaContext(): SchemaStore {
	if (hasContext(SCHEMA_STORE_KEY)) {
		return getContext<SchemaStore>(SCHEMA_STORE_KEY);
	}
	return schemaSingleton;
}

export function getEnginesContext(): EnginesStore {
	if (hasContext(ENGINES_STORE_KEY)) {
		return getContext<EnginesStore>(ENGINES_STORE_KEY);
	}
	return enginesSingleton;
}

export function getConfigContext(): ConfigStore {
	if (hasContext(CONFIG_STORE_KEY)) {
		return getContext<ConfigStore>(CONFIG_STORE_KEY);
	}
	return configSingleton;
}

// Stores interface for type safety
export interface AppStores {
	analysis: AnalysisStore;
	datasource: DatasourceStore;
	schema: SchemaStore;
	engines: EnginesStore;
	config: ConfigStore;
}

// Initialize all stores and set them in context (call from root layout)
export function initializeStores(): AppStores {
	const stores: AppStores = {
		analysis: createAnalysisStore(),
		datasource: createDatasourceStore(),
		schema: createSchemaStore(),
		engines: createEnginesStore(),
		config: createConfigStore()
	};

	setAnalysisContext(stores.analysis);
	setDatasourceContext(stores.datasource);
	setSchemaContext(stores.schema);
	setEnginesContext(stores.engines);
	setConfigContext(stores.config);

	return stores;
}

// Re-export store classes for direct use if needed
export { AnalysisStore, DatasourceStore, SchemaStore, EnginesStore, ConfigStore };

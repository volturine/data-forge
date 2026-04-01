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
import { AuthStore } from './auth.svelte';

// Import singletons for fallback (backward compatibility during migration)
import { analysisStore as analysisSingleton } from './analysis.svelte';
import { datasourceStore as datasourceSingleton } from './datasource.svelte';
import { schemaStore as schemaSingleton } from './schema.svelte';
import { enginesStore as enginesSingleton } from './engines.svelte';
import { configStore as configSingleton } from './config.svelte';
import { authStore as authSingleton } from './auth.svelte';

// Context keys (using Symbols for uniqueness)
const ANALYSIS_STORE_KEY = Symbol('analysis-store');
const DATASOURCE_STORE_KEY = Symbol('datasource-store');
const SCHEMA_STORE_KEY = Symbol('schema-store');
const ENGINES_STORE_KEY = Symbol('engines-store');
const CONFIG_STORE_KEY = Symbol('config-store');
const AUTH_STORE_KEY = Symbol('auth-store');

function makeStoreContext<T>(key: symbol, fallback: T) {
	return {
		set: (store: T) => setContext(key, store),
		get: (): T => (hasContext(key) ? getContext<T>(key) : fallback)
	};
}

const analysisCtx = makeStoreContext(ANALYSIS_STORE_KEY, analysisSingleton);
const datasourceCtx = makeStoreContext(DATASOURCE_STORE_KEY, datasourceSingleton);
const schemaCtx = makeStoreContext(SCHEMA_STORE_KEY, schemaSingleton);
const enginesCtx = makeStoreContext(ENGINES_STORE_KEY, enginesSingleton);
const configCtx = makeStoreContext(CONFIG_STORE_KEY, configSingleton);
const authCtx = makeStoreContext(AUTH_STORE_KEY, authSingleton);

export const setAnalysisContext = analysisCtx.set;
export const getAnalysisContext = analysisCtx.get;
export const setDatasourceContext = datasourceCtx.set;
export const getDatasourceContext = datasourceCtx.get;
export const setSchemaContext = schemaCtx.set;
export const getSchemaContext = schemaCtx.get;
export const setEnginesContext = enginesCtx.set;
export const getEnginesContext = enginesCtx.get;
export const setConfigContext = configCtx.set;
export const getConfigContext = configCtx.get;
export const setAuthContext = authCtx.set;
export const getAuthContext = authCtx.get;

// Stores interface for type safety
export interface AppStores {
	analysis: AnalysisStore;
	datasource: DatasourceStore;
	schema: SchemaStore;
	engines: EnginesStore;
	config: ConfigStore;
	auth: AuthStore;
}

// Initialize all stores and set them in context (call from root layout)
export function initializeStores(): AppStores {
	const stores: AppStores = {
		analysis: new AnalysisStore(),
		datasource: new DatasourceStore(),
		schema: new SchemaStore(),
		engines: new EnginesStore(),
		config: new ConfigStore(),
		auth: new AuthStore()
	};

	setAnalysisContext(stores.analysis);
	setDatasourceContext(stores.datasource);
	setSchemaContext(stores.schema);
	setEnginesContext(stores.engines);
	setConfigContext(stores.config);
	setAuthContext(stores.auth);

	return stores;
}

// Re-export store classes for direct use if needed
export { AnalysisStore, DatasourceStore, SchemaStore, EnginesStore, ConfigStore, AuthStore };

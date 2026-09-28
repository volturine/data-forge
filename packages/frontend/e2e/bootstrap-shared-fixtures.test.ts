import {
	E2E_SHARED_NAMESPACE_A,
	E2E_SHARED_NAMESPACE_B,
	E2E_SHARED_NAMESPACE_DATASOURCE,
	expect,
	test
} from '../tests/fixtures.js';
import { createDatasource, ensureNamespace } from '../tests/utils/api.js';
import { DEFAULT_NAMESPACE } from '../tests/utils/namespace.js';

/**
 * The application stack is shared by every Playwright shard. Create the
 * immutable datasets once, before the browser shards start, so fixture setup
 * cannot turn into a cross-container locking race or a burst of duplicate
 * ingestion requests.
 */
test('bootstraps the immutable shared datasets', async ({
	sharedDatasource,
	sharedAuxDatasource,
	sharedHealthCheckDatasource,
	sharedDateDatasource,
	sharedBulkDatasource,
	request
}) => {
	expect(sharedDatasource.id).toBeTruthy();
	expect(sharedAuxDatasource.id).toBeTruthy();
	expect(sharedHealthCheckDatasource.id).toBeTruthy();
	expect(sharedDateDatasource.id).toBeTruthy();
	expect(sharedBulkDatasource.id).toBeTruthy();
	if (process.env.E2E_BOOTSTRAP_NAMESPACE_FIXTURES === '1') {
		await createDatasource(request, E2E_SHARED_NAMESPACE_DATASOURCE, E2E_SHARED_NAMESPACE_A);
		await ensureNamespace(request, E2E_SHARED_NAMESPACE_B);
		await ensureNamespace(request, DEFAULT_NAMESPACE);
	}
});

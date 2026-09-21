import { expect, test } from '../tests/fixtures.js';

/**
 * The application stack is shared by every Playwright shard. Create the
 * immutable datasets once, before the browser shards start, so fixture setup
 * cannot turn into a cross-container locking race or a burst of duplicate
 * ingestion requests.
 */
test('bootstraps the immutable shared datasets', async ({
	sharedDatasource,
	sharedAuxDatasource,
	sharedDateDatasource,
	sharedBulkDatasource
}) => {
	expect(sharedDatasource.id).toBeTruthy();
	expect(sharedAuxDatasource.id).toBeTruthy();
	expect(sharedDateDatasource.id).toBeTruthy();
	expect(sharedBulkDatasource.id).toBeTruthy();
});

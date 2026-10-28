// Safari and Bun ship without Temporal; polyfill must load before any app module
import 'temporal-polyfill/global';
import { appBootstrap } from '#lib/services/app-bootstrap.svelte.js';

export function init(): void {
	void appBootstrap.start();
}

import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import AuthProviders from './AuthProviders.svelte';

describe('AuthProviders', () => {
	test('renders provider actions with their server-owned OAuth endpoints', () => {
		render(AuthProviders);

		expect(screen.getByRole('link', { name: 'Google' })).toHaveAttribute(
			'href',
			'/api/v1/auth/google'
		);
		expect(screen.getByRole('link', { name: 'GitHub' })).toHaveAttribute(
			'href',
			'/api/v1/auth/github'
		);
	});
});

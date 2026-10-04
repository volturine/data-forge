import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import AuthProviders from './AuthProviders.svelte';

describe('AuthProviders', () => {
	test('renders the GitHub OAuth action with its server-owned endpoint', () => {
		render(AuthProviders);

		expect(screen.getByRole('link', { name: 'GitHub' })).toHaveAttribute(
			'href',
			'/api/v1/auth/github'
		);
		expect(screen.queryByRole('link', { name: 'Google' })).not.toBeInTheDocument();
	});
});

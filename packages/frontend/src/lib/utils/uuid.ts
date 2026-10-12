export function uuid(): string {
	const cryptoApi = globalThis.crypto;
	const randomUuid = cryptoApi?.randomUUID;
	if (typeof randomUuid === 'function') {
		return randomUuid.call(cryptoApi);
	}

	const fill = cryptoApi?.getRandomValues;
	if (typeof fill !== 'function') {
		throw new Error('Cryptographically secure random values are unavailable');
	}

	const bytes = new Uint8Array(16);
	fill.call(cryptoApi, bytes);
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;

	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

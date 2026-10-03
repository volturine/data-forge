// Auth pages are public static entry points. They must be rendered into the
// release image instead of relying on the empty SPA fallback, otherwise a
// direct visit can show only the bootstrap spinner until client routing wins.
export const prerender = true;

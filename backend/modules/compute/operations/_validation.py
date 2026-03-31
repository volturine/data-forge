"""Shared validation helpers for compute operations."""

import re

_DUNDER_RE = re.compile(r'(^|[^A-Za-z0-9_])__[^\s]*__')
_REFLECTION_PATTERNS = (
    '__',
    'getattr(',
    'setattr(',
    'delattr(',
    'vars(',
    'dir(',
    'globals(',
    'locals(',
    'object.',
    'type(',
    'super(',
)


def validate_regex_pattern(pattern: str) -> None:
    """Raise ValueError if *pattern* does not compile as a valid Python regex."""
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f'Invalid regex pattern: {e}') from e


def validate_no_reflection_escape(code: str, *, label: str) -> None:
    """Reject obvious dunder and reflection escape patterns."""
    if _DUNDER_RE.search(code):
        raise ValueError(f'{label} contains forbidden dunder access')
    lowered = code.lower()
    for pattern in _REFLECTION_PATTERNS:
        if pattern in lowered:
            raise ValueError(f'{label} contains forbidden pattern: {pattern}')

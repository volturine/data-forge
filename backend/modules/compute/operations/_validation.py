"""Shared validation helpers for compute operations."""

import re


def validate_regex_pattern(pattern: str) -> None:
    """Raise ValueError if *pattern* does not compile as a valid Python regex."""
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f'Invalid regex pattern: {e}') from e

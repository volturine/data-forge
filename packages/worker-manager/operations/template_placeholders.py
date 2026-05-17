import re
from collections.abc import Mapping

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def render_template_placeholders(template: str, row: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in row:
            return str(row[key])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(replace, template)

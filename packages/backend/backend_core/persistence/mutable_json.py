from copy import deepcopy
from typing import Any

from sqlalchemy.ext.mutable import MutableDict


class CopyOnAssignMutableDict(MutableDict[str, Any]):
    """MutableDict that copies the payload when an already-tracked dict is assigned to another attribute.

    Plain MutableDict returns the same instance on coercion, so assigning one ORM
    instance's JSON column to another (e.g. restoring a version into its analysis)
    silently aliases both parents: in-place mutation of one would corrupt history.
    """

    @classmethod
    def coerce(cls, key: str, value: Any) -> MutableDict[str, Any] | None:
        if isinstance(value, cls):
            return cls(deepcopy(dict(value)))
        return super().coerce(key, value)

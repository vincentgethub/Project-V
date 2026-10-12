"""Read SQLAlchemy expression nodes for narrowly scoped offline fault injection."""

from typing import Any

from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.visitors import iterate


def selects_kind(statement: Any, kind: str) -> bool:
    return any(
        isinstance(node, BindParameter)
        and (node.value == kind or isinstance(node.value, (tuple, list)) and kind in node.value)
        for node in iterate(statement)
    )

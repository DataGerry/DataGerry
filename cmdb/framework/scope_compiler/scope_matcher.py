# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Matches one document against a compiled scope filter in Python - the twin of MongoDB for exactly the filter shapes the
compiler emits (phase 9 step 8, ruled R21), so ``can()`` judges an object state no query can reach (a create's or an
edit's new state) the way a list query judges the stored objects. ``tests/integration/framework/
test_integration_scope_matcher_equivalence.py`` pins the two against each other

Supported: ``$and``, ``$or``; a dotted path through documents and arrays; per path ``$elemMatch`` (a document of
conditions, or operators on a scalar element), ``$eq``, ``$in``, ``$nin``, ``$type``, ``$lt`` / ``$lte`` / ``$gt`` /
``$gte``, ``$regex`` (+ ``$options``), ``$not`` (an operator document). A timezone-aware date is compared as naive
UTC, as stored. MongoDB semantics kept: an array matches when an element matches (and the array itself
for equality); a missing field equals ``null``; comparisons only within one type bracket (numbers, texts, dates,
booleans - a boolean is no number); ``$nin`` / ``$not`` match a missing field. Anything else raises ``ValueError`` -
the compiler never emits it
"""
import re
from datetime import datetime, timezone
from typing import Any

# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'document_matches',
]

_MISSING: object = object()
_ORDER: dict[str, Any] = {
    '$lt': lambda left, right: left < right,
    '$lte': lambda left, right: left <= right,
    '$gt': lambda left, right: left > right,
    '$gte': lambda left, right: left >= right,
}
_BSON_TYPES: dict[str, Any] = {
    'string': lambda value: isinstance(value, str),
    'number': lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    'date': lambda value: isinstance(value, datetime),
    'bool': lambda value: isinstance(value, bool),
    'array': lambda value: isinstance(value, list),
}


def document_matches(document: Any, criteria: dict[str, Any]) -> bool:
    """
    Whether a document matches a filter document

    Args:
        document (Any): The document (a dict)
        criteria (dict[str, Any]): The filter

    Raises:
        ValueError: For a filter shape the compiler never emits

    Returns:
        bool: True when every top-level condition holds
    """
    for key, condition in criteria.items():
        if key == '$and':
            if not all(document_matches(document, part) for part in condition):
                return False
        elif key == '$or':
            if not any(document_matches(document, part) for part in condition):
                return False
        elif key.startswith('$'):
            raise ValueError(f"Unsupported top-level operator {key}")
        elif not _path_matches(document, key.split('.'), condition):
            return False

    return True


def _path_matches(document: Any, path: list[str], condition: Any) -> bool:
    """
    Whether the value(s) at a dotted path satisfy a condition - arrays on the way are traversed element by element

    Args:
        document (Any): The (sub)document
        path (list[str]): The remaining path segments
        condition (Any): An operator document, or a value for implicit equality

    Returns:
        bool: True when the condition holds
    """
    if path and isinstance(document, list):
        return any(_path_matches(item, path, condition) for item in document if isinstance(item, dict)) \
            or (_is_negation(condition) and not any(isinstance(item, dict) for item in document))

    if not path:
        return _value_matches(document, condition)

    value: Any = document.get(path[0], _MISSING) if isinstance(document, dict) else _MISSING

    if value is _MISSING and len(path) > 1:
        return _value_matches(_MISSING, condition)

    return _path_matches(value, path[1:], condition)


def _is_negation(condition: Any) -> bool:
    """
    Whether a condition is satisfied by a missing value - ``$nin`` / ``$not`` / ``$ne``-style

    Args:
        condition (Any): The condition

    Returns:
        bool: True for an operator document whose operators all match a missing value
    """
    return isinstance(condition, dict) and bool(condition) and all(op in ('$nin', '$not') for op in condition)


def _value_matches(value: Any, condition: Any) -> bool:
    """
    Whether one value satisfies a condition

    Args:
        value (Any): The value at the path, or the missing marker
        condition (Any): An operator document, or a value for implicit equality

    Returns:
        bool: True when every operator holds
    """
    if not (isinstance(condition, dict) and condition and all(key.startswith('$') for key in condition)):
        return _equals_any(value, [condition])

    options: str = condition.get('$options', '')

    for operator, operand in condition.items():
        if operator != '$options' and not _operator_holds(value, operator, operand, options):
            return False

    return True


def _operator_holds(value: Any, operator: str, operand: Any, options: str) -> bool:
    """
    Whether one operator holds on a value

    Args:
        value (Any): The value, or the missing marker
        operator (str): The operator
        operand (Any): Its operand
        options (str): The ``$options`` of a ``$regex``

    Raises:
        ValueError: For an operator the compiler never emits

    Returns:
        bool: True when it holds
    """
    if operator == '$elemMatch':
        return isinstance(value, list) and any(_element_matches(item, operand) for item in value)

    if operator == '$eq':
        return _equals_any(value, [operand])

    if operator == '$in':
        return _equals_any(value, list(operand))

    if operator == '$nin':
        return not _equals_any(value, list(operand))

    if operator == '$not':
        return not _value_matches(value, operand)

    if operator == '$type':
        return value is not _MISSING and any(_BSON_TYPES[operand](item) for item in _candidates(value))

    if operator == '$regex':
        flags: int = re.IGNORECASE if 'i' in options else 0

        return any(isinstance(item, str) and re.search(operand, item, flags) for item in _candidates(value))

    if operator in _ORDER:
        return any(_comparable(item, operand) and _ORDER[operator](_naive(item), _naive(operand))
                   for item in _candidates(value))

    raise ValueError(f"Unsupported operator {operator}")


def _element_matches(item: Any, operand: dict[str, Any]) -> bool:
    """
    Whether one array element satisfies an ``$elemMatch``: a document its conditions, a scalar its operators

    Args:
        item (Any): The element
        operand (dict[str, Any]): The ``$elemMatch`` operand - conditions on fields, or operators (``$gte`` ...)

    Returns:
        bool: True when it holds
    """
    if operand and all(key.startswith('$') for key in operand):
        return not isinstance(item, (dict, list)) and _value_matches(item, operand)

    return isinstance(item, dict) and document_matches(item, operand)


def _candidates(value: Any) -> list[Any]:
    """
    The values a comparison is tried on: an array's elements and the array itself, else the value

    Args:
        value (Any): The value, or the missing marker

    Returns:
        list[Any]: The candidates; empty for a missing value
    """
    if value is _MISSING:
        return []

    return [*value, value] if isinstance(value, list) else [value]


def _equals_any(value: Any, operands: list[Any]) -> bool:
    """
    MongoDB equality of a value against any of the operands - a missing value equals ``null``, an array matches when
    it or one of its elements equals

    Args:
        value (Any): The value, or the missing marker
        operands (list[Any]): The values compared with

    Returns:
        bool: True when one operand equals
    """
    candidates: list[Any] = [None] if value is _MISSING else _candidates(value)

    return any(_same(candidate, operand) for candidate in candidates for operand in operands)


def _same(left: Any, right: Any) -> bool:
    """
    BSON equality: equal values of the same type bracket - a boolean never equals a number

    Args:
        left (Any): One value
        right (Any): The other

    Returns:
        bool: True when equal
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right

    return (_comparable(left, right) and _naive(left) == _naive(right)) or (left is None and right is None)


def _naive(value: Any) -> Any:
    """
    A date as naive UTC - how MongoDB hands stored dates back; any other value unchanged

    Args:
        value (Any): A value

    Returns:
        Any: The value, a timezone-aware date converted
    """
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def _comparable(left: Any, right: Any) -> bool:
    """
    Whether two values sit in the same BSON type bracket

    Args:
        left (Any): One value
        right (Any): The other

    Returns:
        bool: True for two numbers (no booleans), two texts, two dates, two arrays or two documents
    """
    for bracket in ((int, float), (str,), (datetime,), (list,), (dict,)):
        if isinstance(left, bracket) and isinstance(right, bracket) \
                and not isinstance(left, bool) and not isinstance(right, bool):
            return True

    return False

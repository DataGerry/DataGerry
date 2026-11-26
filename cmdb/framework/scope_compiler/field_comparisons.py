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
Compiles a cast scope into a MongoDB filter on the object's field entries (phase 9 step 2, ruled R1, R4, R6, R8, R9)

The conditions must all match: the filter is an ``$and`` of one fragment per condition, each an ``$elemMatch`` on the
named field entry (the shared ``database.field_query_fragments``). What "empty" is: no entry, ``null``, ``''`` or
``[]`` - ``exists`` the opposite, ``is_empty`` also matching an object without the entry; ``not_equals`` and
``not_in`` never match an empty or missing field (a missing field grants no access), nor a value of another type than
the field's (a number stored as text, T583 - a negation would otherwise grant access by a mistyped value). Dates
compare day-granularly; a relative date ``{days_ago: n}`` is resolved against the evaluation day (UTC). ``contains``
is a substring on a text, the membership of an id on a multi-value person field. Values are compared on the field's
stored type only - a value stored with another type never matches (fail closed, T583)

A user token becomes the person / person group ids it stands for, resolved per user (``ScopeContext``); an unresolved
token matches nothing. The location and network conditions read the object's materialised scope block (``_scope``,
phase 10): ``{within: L}`` is L itself or an object whose location chain names L, ``{in_network: N}`` an object whose
networks name the subnet or supernet N, ``{in_network: <CIDR>}`` an object with an interface address inside the
range - also one in no stored subnet (D4), ``{related_to: A, relation?: R}`` an object whose related list names A
(through a relation R)
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectScopeKey, CmdbObjectScopeRelatedKey
from cmdb.models.object_model.object_scope_block import network_bounds, scope_path
from cmdb.models.type_model import FieldType
from cmdb.database.field_query_fragments import (
    FIELDS_PATH,
    contains_fragment,
    day_granular_fragment,
    elem_match,
    end_of_day,
    no_entry,
    starts_with_fragment,
)
from cmdb.framework.scope_compiler.scope_compiler_constants import (
    DATE_FORMAT,
    KIND_BSON_TYPES,
    MULTIPLE_PERSON_KIND,
    RELATION_FILTER_KEY,
    RelativeDateKey,
    ScopeBlockKey,
    ScopeBlockKind,
    ScopeOperator,
)
from cmdb.framework.scope_compiler.scope_fields import ScopeField
from cmdb.framework.scope_compiler.scope_grammar import block_kind, is_relative_date, is_user_token
from cmdb.framework.scope_compiler.scope_resolution import ScopeContext
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'EMPTY_VALUES',
    'compile_scope',
    'compile_block',
    'compile_condition',
    'within_fragment',
    'in_network_fragment',
    'related_to_fragment',
    'resolve_date',
]

# What counts as empty in a field entry (ruled R6) - a missing entry too, matched separately
EMPTY_VALUES: list[Any] = [None, '', []]

# The comparisons that map to one MongoDB operator
_ORDER_OPERATORS: dict[ScopeOperator, str] = {
    ScopeOperator.LT: '$lt',
    ScopeOperator.LTE: '$lte',
    ScopeOperator.GT: '$gt',
    ScopeOperator.GTE: '$gte',
}


def compile_scope(blocks: list[dict[str, Any]], fields: dict[str, ScopeField], now: datetime | None = None,
                  context: ScopeContext | None = None) -> dict[str, Any]:
    """
    The MongoDB filter of a cast scope - every condition must match

    Args:
        blocks (list[dict[str, Any]]): The cast conditions
        fields (dict[str, ScopeField]): The resolved fields of the comparisons, by name
        now (datetime | None): The evaluation instant relative dates resolve against; now (UTC) when None
        context (ScopeContext | None): The user's resolved tokens; none resolved when None

    Returns:
        dict[str, Any]: ``{'$and': [...]}``, one fragment per condition
    """
    moment: datetime = now or datetime.now(timezone.utc)
    resolved: ScopeContext = context or ScopeContext()

    return {'$and': [compile_block(block, fields, moment, resolved) for block in blocks]}


def compile_block(block: dict[str, Any], fields: dict[str, ScopeField], now: datetime,
                  context: ScopeContext) -> dict[str, Any]:
    """
    The filter fragment of one cast condition of any kind

    Args:
        block (dict[str, Any]): The condition
        fields (dict[str, ScopeField]): The resolved fields, by name
        now (datetime): The evaluation instant
        context (ScopeContext): The user's resolved tokens

    Returns:
        dict[str, Any]: The fragment
    """
    kind: ScopeBlockKind | None = block_kind(block)

    if kind == ScopeBlockKind.WITHIN:
        return within_fragment(block[kind.value])

    if kind == ScopeBlockKind.IN_NETWORK:
        return in_network_fragment(block[kind.value])

    if kind == ScopeBlockKind.RELATED_TO:
        return related_to_fragment(block[kind.value], block.get(RELATION_FILTER_KEY))

    value: Any = block.get(ScopeBlockKey.VALUE.value)

    if is_user_token(value):
        return {FIELDS_PATH: elem_match(block[ScopeBlockKey.FIELD.value], {'$in': context.token_ids(value)})}

    return compile_condition(block, fields[block[ScopeBlockKey.FIELD.value]], now)


def within_fragment(location_id: int) -> dict[str, Any]:
    """
    The objects in a location's subtree: the location itself and every object whose location chain names it (R17)

    Args:
        location_id (int): The location's object id

    Returns:
        dict[str, Any]: The fragment
    """
    return {'$or': [{CmdbObjectKey.PUBLIC_ID.value: location_id},
                    {scope_path(CmdbObjectScopeKey.LOCATIONS): location_id}]}


def in_network_fragment(network: int | str) -> dict[str, Any]:
    """
    The objects in a network: a subnet or supernet id named by the networks, a CIDR containing an interface address

    Args:
        network (int | str): A network object id, or a CIDR in its canonical network form

    Returns:
        dict[str, Any]: The fragment
    """
    if isinstance(network, str):
        lower, upper = network_bounds(network)

        return {scope_path(CmdbObjectScopeKey.IPS): {'$elemMatch': {'$gte': lower, '$lte': upper}}}

    return {scope_path(CmdbObjectScopeKey.NETWORKS): network}


def related_to_fragment(object_id: int, relation_id: int | None = None) -> dict[str, Any]:
    """
    The objects an object relation links to an object, either direction - optionally of one relation only

    Args:
        object_id (int): The anchor object's id
        relation_id (int | None): The relation (definition) the link must be an instance of. Defaults to None (any)

    Returns:
        dict[str, Any]: The fragment
    """
    entry: dict[str, int] = {CmdbObjectScopeRelatedKey.OBJECT.value: object_id}

    if relation_id is not None:
        entry[CmdbObjectScopeRelatedKey.RELATION.value] = relation_id

    return {scope_path(CmdbObjectScopeKey.RELATED): {'$elemMatch': entry}}


def compile_condition(block: dict[str, Any], field: ScopeField, now: datetime) -> dict[str, Any]:
    """
    The filter fragment of one cast field comparison with a fixed value

    Args:
        block (dict[str, Any]): The condition
        field (ScopeField): Its resolved field
        now (datetime): The evaluation instant

    Returns:
        dict[str, Any]: The fragment
    """
    name: str = block[ScopeBlockKey.FIELD.value]
    operator: ScopeOperator = ScopeOperator(block[ScopeBlockKey.OP.value])

    if operator == ScopeOperator.IS_EMPTY:
        return {'$or': [{FIELDS_PATH: elem_match(name, {'$in': EMPTY_VALUES})}, no_entry(name)]}

    if operator == ScopeOperator.EXISTS:
        return {FIELDS_PATH: elem_match(name, {'$nin': EMPTY_VALUES})}

    value: Any = block.get(ScopeBlockKey.VALUE.value)

    if field.kind == FieldType.DATE.value:
        return {FIELDS_PATH: elem_match(name, _date_fragment(operator, value, now))}

    return {FIELDS_PATH: elem_match(name, _value_fragment(operator, value, field))}


def _value_fragment(operator: ScopeOperator, value: Any, field: ScopeField) -> dict[str, Any]:
    """
    The value comparison of a condition on a field that is no date

    Args:
        operator (ScopeOperator): The comparison
        value (Any): The cast value
        field (ScopeField): The field

    Returns:
        dict[str, Any]: The fragment for the entry's value
    """
    if operator == ScopeOperator.EQUALS:
        return {'$eq': value}

    if operator == ScopeOperator.NOT_EQUALS:
        return {'$nin': [value, *EMPTY_VALUES], '$type': KIND_BSON_TYPES[field.kind]}

    if operator == ScopeOperator.IN:
        return {'$in': list(value)}

    if operator == ScopeOperator.NOT_IN:
        return {'$nin': [*value, *EMPTY_VALUES], '$type': KIND_BSON_TYPES[field.kind]}

    if operator == ScopeOperator.CONTAINS:
        # A multi-value person field holds a list of ids: equality on an array tests membership
        return {'$eq': value} if field.kind == MULTIPLE_PERSON_KIND else contains_fragment(value)

    if operator == ScopeOperator.STARTS_WITH:
        return starts_with_fragment(value)

    if operator == ScopeOperator.BETWEEN:
        return {'$gte': value[0], '$lte': value[1]}

    return {_ORDER_OPERATORS[operator]: value}


def _date_fragment(operator: ScopeOperator, value: Any, now: datetime) -> dict[str, Any]:
    """
    The day-granular comparison of a condition on a date field

    Args:
        operator (ScopeOperator): The comparison
        value (Any): A ``YYYY-MM-DD`` text, a relative date, or a pair of them for ``between``
        now (datetime): The evaluation instant

    Returns:
        dict[str, Any]: The fragment for the entry's value
    """
    if operator == ScopeOperator.BETWEEN:
        low, high = sorted((resolve_date(value[0], now), resolve_date(value[1], now)))

        return {'$gte': low, '$lte': end_of_day(high)}

    day: datetime = resolve_date(value, now)

    if operator == ScopeOperator.EQUALS:
        return day_granular_fragment('$eq', day) or {}

    if operator == ScopeOperator.NOT_EQUALS:
        return {**(day_granular_fragment('$ne', day) or {}), '$type': KIND_BSON_TYPES[FieldType.DATE.value]}

    mongo_operator: str = _ORDER_OPERATORS[operator]

    return day_granular_fragment(mongo_operator, day) or {mongo_operator: day}


def resolve_date(value: Any, now: datetime) -> datetime:
    """
    The day a date value names, at midnight - a relative date counted back from the evaluation day (UTC)

    Stored dates are read as naive UTC timestamps, so the day is naive too

    Args:
        value (Any): A ``YYYY-MM-DD`` text or ``{days_ago: n}``
        now (datetime): The evaluation instant

    Returns:
        datetime: The day at 00:00:00, naive
    """
    if is_relative_date(value):
        today: datetime = now.astimezone(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)

        return today - timedelta(days=value[RelativeDateKey.DAYS_AGO.value])

    return datetime.strptime(value, DATE_FORMAT)

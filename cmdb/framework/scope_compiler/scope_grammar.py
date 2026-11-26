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
The shape of an access scope (phase 9 step 1, ruled R1, R2, R5): ``"*"`` or a flat list of 1 to 50 conditions that
must all match - alternatives are separate assignments, which add up. A condition is ``{field, op, value}``: a field
name, a ``ScopeOperator``, and the value the operator takes - none (``exists``, ``is_empty``), a list of 1 to 1000
(``in``, ``not_in``), a pair (``between``) or one. A value is a typed scalar - a text of at most 1000 characters, a
number, true / false - or a relative date ``{days_ago: n}``; never any other document, so nothing a client sends can
become a database operator. Whether the field exists and the value fits it is the Types' question (``scope_casting``)

Beside the comparisons stand the blocks (phase 9 steps 5 + 6, ruled R16): ``{within: <location object id>}``,
``{in_network: <subnet / supernet object id, or a CIDR>}`` and ``{related_to: <object id>, relation?: <relation id>}``
(phase 11, D9 + D11). A person selector comparison may take a user token as
its value - ``{user: person}`` / ``{user: groups}`` (step 4, R13) - in ``equals``, ``in`` (instead of the list) and
``contains``; never inside a list

The canonical form sorts the conditions and the values of ``in`` / ``not_in`` (each once) and writes a CIDR in its
network form - two spellings of one scope are stored once under the assignments' unique index; a ``between`` pair keeps
its order
"""
import ipaddress
import json
import math
from typing import Any

from cmdb.models.access_model import UNCONDITIONAL_SCOPE
from cmdb.framework.scope_compiler.scope_compiler_constants import (
    BETWEEN_BOUNDS,
    LIST_OPERATORS,
    MAX_DAYS_AGO,
    MAX_FIELD_NAME_LENGTH,
    MAX_LIST_VALUES,
    MAX_SCOPE_BLOCKS,
    MAX_TEXT_LENGTH,
    NO_VALUE_OPERATORS,
    PAIR_OPERATORS,
    RELATION_FILTER_KEY,
    TOKEN_OPERATORS,
    RelativeDateKey,
    ScopeBlockKey,
    ScopeBlockKind,
    ScopeMessage,
    ScopeOperator,
    UserToken,
    UserTokenKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'scope_shape_problems',
    'canonical_blocks',
    'is_relative_date',
    'is_user_token',
    'block_kind',
    'network_value',
]

BLOCK_KEYS: frozenset[str] = frozenset(key.value for key in ScopeBlockKey)
OPERATORS: frozenset[str] = frozenset(operator.value for operator in ScopeOperator)
TOKENS: frozenset[str] = frozenset(token.value for token in UserToken)
# The sort kind shared by every number - an int and a float of one value are one list value
_NUMBER_KIND: str = 'number'


def block_kind(block: Any) -> ScopeBlockKind | None:
    """
    Which block a condition is

    Args:
        block (Any): A condition

    Returns:
        ScopeBlockKind | None: ``within`` / ``in_network`` for a document holding exactly that key, ``related_to`` for
            one holding it and at most ``relation`` beside it; None otherwise (a field comparison, or no condition)
    """
    if not isinstance(block, dict) or not block:
        return None

    keys: set[Any] = set(block)

    if len(keys) == 1 and keys <= {ScopeBlockKind.WITHIN.value, ScopeBlockKind.IN_NETWORK.value}:
        return ScopeBlockKind(next(iter(keys)))

    if ScopeBlockKind.RELATED_TO.value in keys and keys <= {ScopeBlockKind.RELATED_TO.value, RELATION_FILTER_KEY}:
        return ScopeBlockKind.RELATED_TO

    return None


def scope_shape_problems(scope: Any) -> list[str]:
    """
    Judges a scope's shape - every problem, in order

    Args:
        scope (Any): The scope as sent

    Returns:
        list[str]: The problems; empty for ``"*"`` and for a well-formed condition list
    """
    if scope == UNCONDITIONAL_SCOPE:
        return []

    if not isinstance(scope, list):
        return [ScopeMessage.NOT_A_LIST.value]

    if not scope:
        return [ScopeMessage.EMPTY.value]

    if len(scope) > MAX_SCOPE_BLOCKS:
        return [ScopeMessage.TOO_MANY_BLOCKS.value.format(limit=MAX_SCOPE_BLOCKS, count=len(scope))]

    return [problem for position, block in enumerate(scope, start=1) for problem in block_problems(position, block)]


def block_problems(position: int, block: Any) -> list[str]:
    """
    Judges one condition's shape

    Args:
        position (int): Its position in the scope, from 1
        block (Any): The condition as sent

    Returns:
        list[str]: The problems, empty when well-formed
    """
    if not isinstance(block, dict):
        return [ScopeMessage.NOT_A_BLOCK.value.format(position=position)]

    kind: ScopeBlockKind | None = block_kind(block)

    if kind == ScopeBlockKind.WITHIN:
        return [] if _is_id(block[kind.value]) else [ScopeMessage.BAD_LOCATION.value.format(position=position)]

    if kind == ScopeBlockKind.RELATED_TO:
        return [] if _is_id(block[kind.value]) and (RELATION_FILTER_KEY not in block
                                                    or _is_id(block[RELATION_FILTER_KEY])) else [
            ScopeMessage.BAD_RELATED_TO.value.format(position=position)]

    if kind == ScopeBlockKind.IN_NETWORK:
        return [] if network_value(block[kind.value]) is not None else [
            ScopeMessage.BAD_NETWORK.value.format(position=position, value=json.dumps(block[kind.value], default=str))]

    unknown: list[str] = sorted(str(key) for key in block if key not in BLOCK_KEYS)

    if unknown:
        return [ScopeMessage.UNKNOWN_KEYS.value.format(position=position, keys=unknown)]

    field: Any = block.get(ScopeBlockKey.FIELD.value)

    if not isinstance(field, str) or not field.strip() or len(field) > MAX_FIELD_NAME_LENGTH:
        return [ScopeMessage.BAD_FIELD.value.format(position=position, limit=MAX_FIELD_NAME_LENGTH)]

    operator: Any = block.get(ScopeBlockKey.OP.value)

    if operator not in OPERATORS:
        return [ScopeMessage.UNKNOWN_OPERATOR.value.format(position=position, op=operator)]

    return value_problems(position, ScopeOperator(operator), block)


def value_problems(position: int, operator: ScopeOperator, block: dict[str, Any]) -> list[str]:
    """
    Judges whether a condition carries the value its operator takes

    Args:
        position (int): Its position in the scope, from 1
        operator (ScopeOperator): The condition's operator
        block (dict[str, Any]): The condition

    Returns:
        list[str]: The problems, empty when the value fits the operator
    """
    has_value: bool = ScopeBlockKey.VALUE.value in block
    value: Any = block.get(ScopeBlockKey.VALUE.value)

    if operator in NO_VALUE_OPERATORS:
        return [ScopeMessage.VALUE_NOT_ALLOWED.value.format(position=position, op=operator.value)] if has_value else []

    if not has_value:
        return [ScopeMessage.VALUE_MISSING.value.format(position=position, op=operator.value)]

    if is_user_token(value) or (isinstance(value, dict) and UserTokenKey.USER.value in value):
        return _token_problems(position, operator, value)

    if operator in LIST_OPERATORS:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_LIST_VALUES:
            return [ScopeMessage.NOT_A_LIST_VALUE.value.format(position=position, op=operator.value,
                                                               limit=MAX_LIST_VALUES)]

        return _scalar_problems(position, value)

    if operator in PAIR_OPERATORS:
        if not isinstance(value, list) or len(value) != BETWEEN_BOUNDS:
            return [ScopeMessage.NOT_A_PAIR.value.format(position=position)]

        return _scalar_problems(position, value)

    return _scalar_problems(position, [value])


def _token_problems(position: int, operator: ScopeOperator, value: Any) -> list[str]:
    """
    Judges a user token as a condition's whole value

    Args:
        position (int): The condition's position, from 1
        operator (ScopeOperator): The condition's operator
        value (Any): The value - a document holding the ``user`` key

    Returns:
        list[str]: The problems, empty for ``{user: person}`` / ``{user: groups}`` in an operator taking one
    """
    if not is_user_token(value):
        return [ScopeMessage.BAD_TOKEN.value.format(position=position, value=json.dumps(value, default=str))]

    if operator not in TOKEN_OPERATORS:
        return [ScopeMessage.TOKEN_NOT_FOR_OPERATOR.value.format(position=position)]

    return []


def _scalar_problems(position: int, values: list[Any]) -> list[str]:
    """
    Judges the values of one condition: typed scalars or a relative date, each once named

    Args:
        position (int): The condition's position, from 1
        values (list[Any]): Its values

    Returns:
        list[str]: The problems, each once
    """
    problems: list[str] = []

    for value in values:
        problem: str | None = _scalar_problem(position, value)

        if problem and problem not in problems:
            problems.append(problem)

    return problems


def _scalar_problem(position: int, value: Any) -> str | None:
    """
    Judges one value

    Args:
        position (int): The condition's position, from 1
        value (Any): The value

    Returns:
        str | None: The problem, or None for a text within the cap, a finite number, a boolean or a relative date
    """
    if isinstance(value, dict):
        days: Any = value.get(RelativeDateKey.DAYS_AGO.value)

        if set(value) != {RelativeDateKey.DAYS_AGO.value}:
            return ScopeMessage.NOT_A_SCALAR.value.format(position=position, value=json.dumps(value, default=str))

        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= MAX_DAYS_AGO:
            return ScopeMessage.BAD_RELATIVE_DATE.value.format(position=position, limit=MAX_DAYS_AGO)

        return None

    if isinstance(value, str):
        return ScopeMessage.TEXT_TOO_LONG.value.format(position=position, limit=MAX_TEXT_LENGTH) \
            if len(value) > MAX_TEXT_LENGTH else None

    if isinstance(value, float) and not math.isfinite(value):
        return ScopeMessage.NOT_A_SCALAR.value.format(position=position, value=value)

    if isinstance(value, (bool, int, float)):
        return None

    return ScopeMessage.NOT_A_SCALAR.value.format(position=position, value=json.dumps(value, default=str))


def is_user_token(value: Any) -> bool:
    """
    Whether a value is a user token ``{user: person}`` / ``{user: groups}``

    Args:
        value (Any): A condition's value

    Returns:
        bool: True for exactly one of the two tokens
    """
    return isinstance(value, dict) and set(value) == {UserTokenKey.USER.value} \
        and value[UserTokenKey.USER.value] in TOKENS


def network_value(value: Any) -> int | str | None:
    """
    An ``in_network`` value in its canonical form

    Args:
        value (Any): The value as sent

    Returns:
        int | str | None: The object id; a CIDR as its network (``10.0.0.5/8`` -> ``10.0.0.0/8``); None when it is
            neither
    """
    if _is_id(value):
        return value

    if not isinstance(value, str) or '/' not in value or len(value) > MAX_TEXT_LENGTH:
        return None

    try:
        return str(ipaddress.ip_network(value.strip(), strict=False))
    except ValueError:
        return None


def _is_id(value: Any) -> bool:
    """
    Whether a value is an object id - a whole number from 1, never a boolean

    Args:
        value (Any): The value

    Returns:
        bool: True for an id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def is_relative_date(value: Any) -> bool:
    """
    Whether a value is a relative date ``{days_ago: n}``

    Args:
        value (Any): A condition's value

    Returns:
        bool: True for the relative form
    """
    return isinstance(value, dict) and RelativeDateKey.DAYS_AGO.value in value


def canonical_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The one spelling of a well-formed condition list: each condition's keys sorted, the values of ``in`` / ``not_in``
    sorted and each once, the conditions sorted - a ``between`` pair keeps its order

    Args:
        blocks (list[dict[str, Any]]): The conditions, shape-checked

    Returns:
        list[dict[str, Any]]: New conditions in canonical form
    """
    canonical: list[dict[str, Any]] = []

    for block in blocks:
        if block_kind(block) == ScopeBlockKind.IN_NETWORK:
            canonical.append({ScopeBlockKind.IN_NETWORK.value: network_value(block[ScopeBlockKind.IN_NETWORK.value])})
            continue

        value: Any = block.get(ScopeBlockKey.VALUE.value)

        if block.get(ScopeBlockKey.OP.value) in LIST_OPERATORS and isinstance(value, list):
            unique: dict[tuple[str, float, str], Any] = {}

            for item in value:
                unique.setdefault(_value_key(item), item)

            value = sorted(unique.values(), key=_value_key)

        rebuilt: dict[str, Any] = {key: block[key] for key in sorted(block)}

        if ScopeBlockKey.VALUE.value in block:
            rebuilt[ScopeBlockKey.VALUE.value] = value

        canonical.append(rebuilt)

    return sorted(canonical, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def _value_key(value: Any) -> tuple[str, float, str]:
    """
    A sort and identity key for one scalar: its kind, then its value - numbers in numeric order (1 and 1.0 are one
    value), everything else by its spelling; values of different kinds never compare

    Args:
        value (Any): A scalar

    Returns:
        tuple[str, float, str]: The key
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _NUMBER_KIND, float(value), ''

    return type(value).__name__, 0.0, json.dumps(value, sort_keys=True, default=str)

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
Casts a shape-checked scope against its resolved fields (phase 9 step 3, ruled R7, R8, R12)

Each condition must name a comparable field (``KIND_OPERATORS``: not password, location, ref-section, nor a field in a
multi-data section) with an operator its kind takes. Each value is cast to the field's stored type: a text stays a text
(a select / radio value must be one of the options), a number a number (a numeric text is read as one), an id a whole
number, a checkbox true / false, a date a ``YYYY-MM-DD`` text - or a relative date ``{days_ago: n}``, kept as it is and
resolved at every evaluation. A ``between`` needs its lower bound first. A user token (``{user: person}`` /
``{user: groups}``, R13) stands only on a person selector selecting that kind (PERSON / PERSON_GROUP) and is kept as it
is - resolved per user when evaluated. The one-key blocks (``within``, ``in_network``) name no field and pass unchanged.
Every problem is reported, none stops the rest
"""
import json
from datetime import datetime
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import FieldType
from cmdb.framework.scope_compiler.scope_compiler_constants import (
    DATE_FORMAT,
    ID_KINDS,
    KIND_OPERATORS,
    MULTIPLE_PERSON_KIND,
    LIST_OPERATORS,
    NO_VALUE_OPERATORS,
    OPTION_KINDS,
    PAIR_OPERATORS,
    TEXT_KINDS,
    Expected,
    ScopeBlockKey,
    ScopeMessage,
    ScopeOperator,
    UserToken,
    UserTokenKey,
)
from cmdb.framework.scope_compiler.scope_fields import ScopeField
from cmdb.framework.scope_compiler.scope_grammar import is_relative_date, is_user_token
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'cast_scope',
    'cast_value',
]


# The special type a user token's ids carry - the selector must select it
TOKEN_MARKERS: dict[str, str] = {
    UserToken.PERSON.value: SpecialType.PERSON.value,
    UserToken.GROUPS.value: SpecialType.PERSON_GROUP.value,
}


class ValueMisfit(ValueError):
    """
    A condition value that does not fit its field's kind - carries what the kind takes
    """
    def __init__(self, expected: Expected) -> None:
        super().__init__(expected.value)
        self.expected: Expected = expected


def cast_scope(blocks: list[dict[str, Any]], fields: dict[str, ScopeField]
               ) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Casts every condition of a shape-checked scope against its resolved fields

    Args:
        blocks (list[dict[str, Any]]): The conditions, shape-checked
        fields (dict[str, ScopeField]): The fields resolved from the role's Types - a name the resolution refused is
            absent and its conditions are skipped (that problem is the resolution's)

    Returns:
        tuple[list[dict[str, Any]], list[str]]: The conditions with cast values, and every problem
    """
    cast: list[dict[str, Any]] = []
    problems: list[str] = []

    for block in blocks:
        if ScopeBlockKey.FIELD.value not in block:
            cast.append(block)
            continue

        name: str = block[ScopeBlockKey.FIELD.value]
        field: ScopeField | None = fields.get(name)

        if field is None:
            cast.append(block)
            continue

        block_problems, cast_block = _cast_block(name, field, block)
        problems.extend(problem for problem in block_problems if problem not in problems)
        cast.append(cast_block)

    return cast, problems


def _cast_block(name: str, field: ScopeField, block: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """
    Casts one condition

    Args:
        name (str): The field name
        field (ScopeField): The resolved field
        block (dict[str, Any]): The condition

    Returns:
        tuple[list[str], dict[str, Any]]: Its problems, and the condition with its value cast (as sent on a problem)
    """
    operator: ScopeOperator = ScopeOperator(block[ScopeBlockKey.OP.value])

    if field.in_mds:
        return [ScopeMessage.IN_MULTI_DATA_SECTION.value.format(field=name)], block

    if field.kind not in KIND_OPERATORS:
        return [ScopeMessage.NOT_COMPARABLE.value.format(field=name, kind=field.kind)], block

    if operator not in KIND_OPERATORS[field.kind]:
        return [ScopeMessage.OPERATOR_NOT_FOR_KIND.value.format(field=name, kind=field.kind, op=operator.value)], block

    if operator in NO_VALUE_OPERATORS:
        return [], block

    raw: Any = block[ScopeBlockKey.VALUE.value]

    if is_user_token(raw):
        return _token_problems(name, field, raw[UserTokenKey.USER.value]), block

    values: list[Any] = raw if operator in LIST_OPERATORS | PAIR_OPERATORS else [raw]
    cast_values: list[Any] = []
    problems: list[str] = []

    for value in values:
        try:
            cast_values.append(cast_value(field, value))
        except ValueMisfit as misfit:
            problems.append(ScopeMessage.VALUE_MISFIT.value.format(value=json.dumps(value, default=str), field=name,
                                                                   expected=misfit.expected.value))
            continue

        if field.kind in OPTION_KINDS and cast_values[-1] not in field.options:
            problems.append(ScopeMessage.NOT_AN_OPTION.value.format(value=cast_values[-1], field=name))

    if problems:
        return problems, block

    if operator in PAIR_OPERATORS and _out_of_order(cast_values):
        return [ScopeMessage.BETWEEN_ORDER.value.format(field=name)], block

    cast_value_or_list: Any = cast_values if operator in LIST_OPERATORS | PAIR_OPERATORS else cast_values[0]

    return [], {**block, ScopeBlockKey.VALUE.value: cast_value_or_list}


def _token_problems(name: str, field: ScopeField, token: str) -> list[str]:
    """
    Judges a user token against its field: a person selector selecting what the token stands for

    Args:
        name (str): The field name
        field (ScopeField): The resolved field
        token (str): ``person`` or ``groups``

    Returns:
        list[str]: The problem, or none
    """
    marker: str = TOKEN_MARKERS[token]

    if field.kind not in (FieldType.PERSON.value, MULTIPLE_PERSON_KIND) or marker not in field.selectable:
        return [ScopeMessage.TOKEN_NOT_FOR_FIELD.value.format(field=name, token=token, kind=marker)]

    return []


def cast_value(field: ScopeField, value: Any) -> Any:
    """
    Casts one value to its field's stored type

    Args:
        field (ScopeField): The resolved field
        value (Any): One shape-checked value

    Raises:
        ValueMisfit: When the value does not fit the field's kind

    Returns:
        Any: The cast value - a relative date as it is
    """
    if field.kind == FieldType.DATE.value:
        return value if is_relative_date(value) else _date_text(value)

    if is_relative_date(value):
        raise ValueMisfit(_expected(field.kind))

    if field.kind in TEXT_KINDS:
        if not isinstance(value, str):
            raise ValueMisfit(Expected.TEXT)

        return value

    if field.kind == FieldType.CHECKBOX.value:
        if not isinstance(value, bool):
            raise ValueMisfit(Expected.BOOLEAN)

        return value

    if field.kind in ID_KINDS:
        return _whole_number(value)

    return _number(value)


def _expected(kind: str) -> Expected:
    """
    What a kind's values are

    Args:
        kind (str): The field kind

    Returns:
        Expected: For the message
    """
    if kind in TEXT_KINDS:
        return Expected.TEXT

    if kind == FieldType.CHECKBOX.value:
        return Expected.BOOLEAN

    return Expected.WHOLE_NUMBER if kind in ID_KINDS else Expected.NUMBER


def _date_text(value: Any) -> str:
    """
    A ``YYYY-MM-DD`` date, as sent

    Args:
        value (Any): The value

    Raises:
        ValueMisfit: When it is not one

    Returns:
        str: The date text
    """
    if not isinstance(value, str):
        raise ValueMisfit(Expected.DATE)

    try:
        datetime.strptime(value, DATE_FORMAT)
    except ValueError as err:
        raise ValueMisfit(Expected.DATE) from err

    return value


def _number(value: Any) -> int | float:
    """
    A number - a numeric text read as one, never a boolean

    Args:
        value (Any): The value

    Raises:
        ValueMisfit: When it is not one

    Returns:
        int | float: The number - whole where it is whole
    """
    if isinstance(value, bool):
        raise ValueMisfit(Expected.NUMBER)

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        try:
            number: float = float(value)
        except ValueError as err:
            raise ValueMisfit(Expected.NUMBER) from err

        return int(number) if number.is_integer() and '.' not in value else number

    raise ValueMisfit(Expected.NUMBER)


def _whole_number(value: Any) -> int:
    """
    A whole number from 0 - an id; a whole-number text read as one

    Args:
        value (Any): The value

    Raises:
        ValueMisfit: When it is not one

    Returns:
        int: The id
    """
    if isinstance(value, bool):
        raise ValueMisfit(Expected.WHOLE_NUMBER)

    if isinstance(value, str) and value.strip().isdigit():
        return int(value)

    if isinstance(value, int) and value >= 0:
        return value

    raise ValueMisfit(Expected.WHOLE_NUMBER)


def _out_of_order(bounds: list[Any]) -> bool:
    """
    Whether a ``between`` pair has its lower bound above its upper bound - relative dates are not compared here (the
    pair is ordered when evaluated)

    Args:
        bounds (list[Any]): The two cast bounds

    Returns:
        bool: True when the first is above the second
    """
    low, high = bounds

    if is_relative_date(low) or is_relative_date(high):
        return False

    return low > high

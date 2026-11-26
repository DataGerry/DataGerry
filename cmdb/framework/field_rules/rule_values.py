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
The values a Field Rule sets - pure

On save each value is cast to its field's kind (``cast_rule_value``): a literal the way a scope value is cast (a select
/ radio value among the options, a date as ``YYYY-MM-DD``), ``null``, ``${now}`` on a date or text field, and
``${user.person}`` on a person selector selecting persons. On a write each stored value becomes what is written
(``resolve_rule_value``): a date as a real date (midnight UTC), ``${now}`` the write's day (date) or instant (text,
ISO),
``${user.person}`` the person linked to the writing user - none when there is none
"""
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.framework.scope_compiler import MULTIPLE_PERSON_KIND, ScopeField, cast_value
from cmdb.framework.scope_compiler.scope_casting import ValueMisfit
from cmdb.framework.field_rules.field_rule_constants import FieldRuleMessage, RuleToken
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'field_kind',
    'cast_rule_value',
    'resolve_rule_value',
]

_PERSON_KINDS: frozenset[str] = frozenset({FieldType.PERSON.value, MULTIPLE_PERSON_KIND})
_TEXT_KINDS: frozenset[str] = frozenset({FieldType.TEXT.value, FieldType.TEXTAREA.value})
_CHOICE_KINDS: frozenset[str] = frozenset({FieldType.SELECT.value, FieldType.RADIO.value})
_PERSON_MARKER: str = 'PERSON'
_DATE_FORMAT: str = '%Y-%m-%d'
PERSON_LIST_EXPECTED: str = 'a list of person ids'


def field_kind(definition: Mapping[str, Any]) -> Any:
    """
    A field's kind as a rule value is cast and resolved - a person selector selecting several is its own kind

    Args:
        definition (Mapping[str, Any]): The field's definition

    Returns:
        Any: The ``FieldType`` value, or ``MULTIPLE_PERSON_KIND``
    """
    kind: Any = definition.get(FieldKey.TYPE.value)

    if kind == FieldType.PERSON.value and definition.get(FieldKey.MULTIPLE.value) is True:
        return MULTIPLE_PERSON_KIND

    return kind


def cast_rule_value(name: str, field: ScopeField, value: Any) -> Any:
    """
    Casts one value a rule would set to its field's kind

    Args:
        name (str): The field's name, for the message
        field (ScopeField): The field, resolved across the rule's Types
        value (Any): The value as sent

    Raises:
        ValueError: The message naming why the value does not fit

    Returns:
        Any: The value to store on the rule
    """
    if value is None:
        return None

    if value == RuleToken.NOW.value:
        if field.kind == FieldType.DATE.value or field.kind in _TEXT_KINDS:
            return value

        raise ValueError(FieldRuleMessage.TOKEN_NOT_FOR_FIELD.value.format(token=value, field=name, kind=field.kind))

    if value == RuleToken.USER_PERSON.value:
        if field.kind in _PERSON_KINDS and _PERSON_MARKER in field.selectable:
            return value

        raise ValueError(FieldRuleMessage.TOKEN_NOT_FOR_FIELD.value.format(token=value, field=name, kind=field.kind))

    if field.kind in _CHOICE_KINDS and value not in field.options:
        raise ValueError(FieldRuleMessage.BAD_VALUE.value.format(field=name, problem=f"'{value}' is no option"))

    try:
        if field.kind == MULTIPLE_PERSON_KIND:
            if not isinstance(value, list):
                raise TypeError(PERSON_LIST_EXPECTED)

            return [cast_value(ScopeField(FieldType.PERSON.value), item) for item in value]

        return cast_value(field, value)
    except (ValueMisfit, TypeError) as err:
        raise ValueError(FieldRuleMessage.BAD_VALUE.value.format(field=name, problem=str(err))) from err


def resolve_rule_value(value: Any, kind: Any, now: datetime, person_id: int | None) -> Any:
    """
    What a stored rule value writes on one write

    Args:
        value (Any): The value as the rule stores it
        kind (Any): The field's kind on the object's Type
        now (datetime): The moment of the write (UTC)
        person_id (int | None): The person linked to the writing user, or None

    Returns:
        Any: The value to write
    """
    if value == RuleToken.NOW.value:
        if kind == FieldType.DATE.value:
            return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

        return now.isoformat()

    if value == RuleToken.USER_PERSON.value:
        if kind != MULTIPLE_PERSON_KIND:
            return person_id

        return [person_id] if person_id is not None else []

    if kind == FieldType.DATE.value and isinstance(value, str):
        return datetime.strptime(value, _DATE_FORMAT).replace(tzinfo=timezone.utc)

    return value

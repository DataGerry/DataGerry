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
The shared value rules of a CmdbObject write: the length cap and the field's pattern

Two rules a CmdbType places on what an object may store in a field, applied wherever an object is
written - the REST write pipeline (insert / update / patch) and the object importer:

  - **the length cap**, per field kind (``FIELD_VALUE_MAX_LENGTHS``): a text or textarea value may
    not be longer than its kind allows. The same cap for every type, so no type has to declare it
  - **the pattern**, per field (``FieldKey.REGEX``): a value must match the regex its field declares,
    read the way the object form reads it (Angular's ``Validators.pattern``): a pattern not starting
    with ``^`` is anchored at the start, one not ending with ``$`` at the end, and nothing else is
    added - so ``a|b`` means ``^a|b$``, exactly as in the form

Both rules judge a VALUE, so a field holding no value (None, the empty string, an empty list) passes
them - whether a value is needed at all is the required-field rule's question. The pattern is tested
against a string or a number (a number the way JavaScript spells it); a value of any other shape is not
pattern-checked. A declared pattern Python cannot compile is skipped with a warning rather than failing
every write of the type.

**A value the write leaves as it was stored is not judged.** An update only answers for what it
changes: an object stored before a cap existed, or before its type gained a pattern, can still be edited
field by field, and the old value is judged the next time someone changes it. A value counts as
unchanged when the stored object holds the same value for the same field in the same place (the
top-level list, or any row of the same multi-data section).

The field values are read from both places a CmdbObject keeps them: the top-level 'fields' list and
the rows of its multi-data sections
"""
import re
from dataclasses import dataclass
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.object_field_value_constants import (
    FieldDefaultError,
    FieldValueError,
    MDS_SECTION_SUFFIX,
    PATTERN_END_ANCHOR,
    PATTERN_START_ANCHOR,
)
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_constants import FIELD_VALUE_MAX_LENGTHS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Where a value sits in a CmdbObject: None for the top-level 'fields' list, else the MDS section id
ValuePlace = str | None


@dataclass(frozen=True)
class FieldValueRule:
    """
    What one CmdbType field allows its value to be

    Attributes:
        max_length (int | None): The most characters the value may hold; None when uncapped
        pattern (re.Pattern | None): The compiled, anchored pattern the value must match; None when the
            field declares none (or one that cannot be compiled)
        regex (str | None): The pattern as the field declares it, quoted back in the error message
    """
    max_length: int | None = None
    pattern: re.Pattern | None = None
    regex: str | None = None


def anchor_field_regex(regex: str) -> str:
    """
    Anchors a field's declared regex the way the object form's pattern validator does

    Args:
        regex (str): The regex as the field declares it

    Returns:
        str: The regex with a leading '^' and a trailing '$' added where it has none
    """
    start: str = '' if regex.startswith(PATTERN_START_ANCHOR) else PATTERN_START_ANCHOR
    end: str = '' if regex.endswith(PATTERN_END_ANCHOR) else PATTERN_END_ANCHOR

    return f'{start}{regex}{end}'


def compile_field_regex(field_name: Any, regex: Any) -> re.Pattern | None:
    """
    Compiles a field's declared regex into the pattern its values are tested against

    Args:
        field_name (Any): The field's name, for the warning a pattern that cannot be compiled logs
        regex (Any): The field's declared ``regex``

    Returns:
        re.Pattern | None: The anchored, compiled pattern; None when the field declares no pattern, or
            one Python cannot compile
    """
    if not isinstance(regex, str) or not regex:
        return None

    try:
        return re.compile(anchor_field_regex(regex))
    except re.error as err:
        LOGGER.warning("[compile_field_regex] Field '%s' declares a regex that cannot be compiled, "
                       "its values are not pattern-checked: %s", field_name, err)
        return None


def build_field_value_rules(type_fields: list[dict[str, Any]] | None) -> dict[str, FieldValueRule]:
    """
    Builds the value rule of every CmdbType field that has one, keyed by field name

    Args:
        type_fields (list[dict[str, Any]] | None): The CmdbType's field definitions

    Returns:
        dict[str, FieldValueRule]: ``{field name: rule}``; a field with neither a cap nor a pattern is
            left out
    """
    rules: dict[str, FieldValueRule] = {}

    for field in type_fields or []:
        name: Any = field.get(FieldKey.NAME.value)
        max_length: int | None = FIELD_VALUE_MAX_LENGTHS.get(field.get(FieldKey.TYPE.value))
        pattern: re.Pattern | None = compile_field_regex(name, field.get(FieldKey.REGEX.value))

        if max_length is not None or pattern is not None:
            rules[name] = FieldValueRule(max_length, pattern, field.get(FieldKey.REGEX.value) if pattern else None)

    return rules


def value_as_pattern_text(value: Any) -> str | None:
    """
    Spells a value the way the object form's pattern validator tests it

    A string is tested as it is and a number the way JavaScript prints it (``5.0`` is ``'5'``); a
    boolean, a date or a list is not text a pattern describes

    Args:
        value (Any): The field value

    Returns:
        str | None: The text to test; None when the value is not pattern-checked
    """
    if isinstance(value, str):
        return value

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)

    return None


def has_no_value(value: Any) -> bool:
    """
    Reports whether a field holds nothing the value rules could judge

    Args:
        value (Any): The field value

    Returns:
        bool: True for None, the empty string and an empty list
    """
    return value is None or value == '' or value == []


def find_value_errors(field_name: str, value: Any, rule: FieldValueRule) -> list[str]:
    """
    Judges one field value against its field's rule

    Args:
        field_name (str): The field's name, for the messages
        value (Any): The value the write stores
        rule (FieldValueRule): The field's rule

    Returns:
        list[str]: One message per broken rule; empty when the value passes
    """
    if has_no_value(value):
        return []

    errors: list[str] = []

    if rule.max_length is not None and isinstance(value, str) and len(value) > rule.max_length:
        errors.append(FieldValueError.TOO_LONG.format(
            field=field_name, length=len(value), max_length=rule.max_length,
        ))

    text: str | None = value_as_pattern_text(value)

    # search(), not fullmatch(): the anchors are part of the pattern, exactly as in the form's test()
    if rule.pattern is not None and text is not None and rule.pattern.search(text) is None:
        errors.append(FieldValueError.PATTERN_MISMATCH.format(field=field_name, regex=rule.regex))

    return errors


def find_default_errors(field_name: str, default: Any, rule: FieldValueRule) -> list[str]:
    """
    Judges a field's declared default against the field's own rule

    Args:
        field_name (str): The field's name, for the messages
        default (Any): The field's declared default value
        rule (FieldValueRule): The field's rule

    Returns:
        list[str]: One message per broken rule, worded about the default; empty when it passes (or when
            there is no default)
    """
    if has_no_value(default):
        return []

    errors: list[str] = []

    if rule.max_length is not None and isinstance(default, str) and len(default) > rule.max_length:
        errors.append(FieldDefaultError.TOO_LONG.format(
            field=field_name, length=len(default), max_length=rule.max_length,
        ))

    text: str | None = value_as_pattern_text(default)

    if rule.pattern is not None and text is not None and rule.pattern.search(text) is None:
        errors.append(FieldDefaultError.PATTERN_MISMATCH.format(field=field_name, regex=rule.regex))

    return errors


def find_default_value_errors(type_fields: list[dict[str, Any]] | None) -> dict[str, list[str]]:
    """
    Judges every field's declared default against that field's own value rules

    The check the CmdbType write, the section-template write and the type-import repair share: a default
    is what every new object of the field starts from, so it has to be a value the object write accepts.
    A field declaring no default passes; a pattern Python cannot compile is skipped, as on the object write

    Args:
        type_fields (list[dict[str, Any]] | None): The field definitions (a flat ``fields`` list)

    Returns:
        dict[str, list[str]]: ``{field name: [messages]}`` for every field whose default breaks a rule;
            empty when all defaults pass
    """
    rules: dict[str, FieldValueRule] = build_field_value_rules(type_fields)
    errors: dict[str, list[str]] = {}

    for field in type_fields or []:
        name: Any = field.get(FieldKey.NAME.value)
        rule: FieldValueRule | None = rules.get(name)

        if rule is None:
            continue

        messages: list[str] = find_default_errors(name, field.get(FieldKey.VALUE.value), rule)

        if messages:
            errors[name] = messages

    return errors


def iter_object_values(object_data: dict[str, Any] | None) -> list[tuple[ValuePlace, Any, Any]]:
    """
    Lists every field value a CmdbObject carries, with where it sits

    Args:
        object_data (dict[str, Any] | None): A CmdbObject document

    Returns:
        list[tuple[ValuePlace, Any, Any]]: ``(place, field name, value)`` for each entry of the
            top-level list (place None) and of every multi-data-section row (place = the section id)
    """
    if not object_data:
        return []

    values: list[tuple[ValuePlace, Any, Any]] = [
        (None, entry.get(CmdbObjectFieldKey.NAME.value), entry.get(CmdbObjectFieldKey.VALUE.value))
        for entry in object_data.get(CmdbObjectKey.FIELDS.value) or []
        if isinstance(entry, dict)
    ]

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        if not isinstance(section, dict):
            continue

        section_id: Any = section.get(CmdbObjectMdsKey.SECTION_ID.value)

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            if not isinstance(row, dict):
                continue

            values.extend(
                (section_id, entry.get(CmdbObjectFieldKey.NAME.value), entry.get(CmdbObjectFieldKey.VALUE.value))
                for entry in row.get(CmdbObjectMdsRowKey.DATA.value) or []
                if isinstance(entry, dict)
            )

    return values


def collect_stored_values(previous_object: dict[str, Any] | None) -> dict[tuple[ValuePlace, Any], list[Any]]:
    """
    Groups the values a stored CmdbObject holds by where they sit and which field they belong to

    Args:
        previous_object (dict[str, Any] | None): The stored CmdbObject document; None for a new object

    Returns:
        dict[tuple[ValuePlace, Any], list[Any]]: ``{(place, field name): [stored values]}``
    """
    stored: dict[tuple[ValuePlace, Any], list[Any]] = {}

    for place, name, value in iter_object_values(previous_object):
        stored.setdefault((place, name), []).append(value)

    return stored


def collect_object_value_errors(
        object_data: dict[str, Any],
        rules: dict[str, FieldValueRule],
        previous_object: dict[str, Any] | None = None) -> list[str]:
    """
    Judges every value a candidate CmdbObject stores against its field's rule

    A value the stored object already holds in the same place is not judged (see the module
    docstring). A message is reported once, however many rows of a section repeat it

    Args:
        object_data (dict[str, Any]): The candidate CmdbObject document
        rules (dict[str, FieldValueRule]): The type's rules (see ``build_field_value_rules``)
        previous_object (dict[str, Any] | None): The stored object an update replaces; None judges
            every value

    Returns:
        list[str]: The error messages, in the order the values appear; empty when every value passes
    """
    if not rules:
        return []

    stored: dict[tuple[ValuePlace, Any], list[Any]] = collect_stored_values(previous_object)
    errors: list[str] = []

    for place, name, value in iter_object_values(object_data):
        rule: FieldValueRule | None = rules.get(name)

        if rule is None or value in stored.get((place, name), []):
            continue

        suffix: str = '' if place is None else MDS_SECTION_SUFFIX.format(section_id=place)

        for message in find_value_errors(name, value, rule):
            if f'{message}{suffix}' not in errors:
                errors.append(f'{message}{suffix}')

    return errors


__all__ = [
    'FieldValueRule',
    'anchor_field_regex',
    'build_field_value_rules',
    'collect_object_value_errors',
    'collect_stored_values',
    'compile_field_regex',
    'find_default_errors',
    'find_default_value_errors',
    'find_value_errors',
    'has_no_value',
    'iter_object_values',
    'value_as_pattern_text',
]

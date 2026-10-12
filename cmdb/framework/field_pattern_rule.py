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
Which field patterns may be written - the ones the browser and the server read the same way

A field's ``regex`` is enforced twice: by the object form (``Validators.pattern`` -> JavaScript ``RegExp`` without
flags, so with the legacy "Annex B" leniency) and by the object write (``object_field_value_rules``, Python's
``regex`` engine). Both anchor it with ``^...$``. Where the two dialects part, the form and the server disagree about
the same value - a value the form accepts is refused, or a pattern is silently not enforced on the server, or the
form cannot even build its validator. So a pattern is judged when it is written (``field_pattern_problem``):

* it must be text (an empty pattern, or none, means "no pattern");
* it must not use a construct the two dialects read differently or only one accepts (``find_dialect_construct``):
  ``\\p`` / ``\\P`` / ``\\A`` / ``\\Z`` / ``\\z`` / ``\\c`` / ``\\k`` escapes, ``\\u{...}``, ``[]`` / ``[^]``, a POSIX
  ``[:...:]`` inside a class, ``{,n}``, any ``(?`` group other than ``(?:`` / lookarounds / ``(?<name>``, and a
  possessive quantifier (``a++``);
* the server must be able to compile it.

``\\d``, ``\\w`` and ``\\b`` are not on the list although the server reads them as Unicode and the browser as ASCII:
the server is then the more lenient side - it accepts a digit the form refuses - so no form user is ever refused a
value the form allowed. The list is deliberately short and conservative: a pattern only the server reads is
also refused, since the form would throw on it
"""
import re
from typing import Any

import regex as regex_engine

from cmdb.framework.object_field_value_constants import (
    DIALECT_CODE_POINT_ESCAPE,
    DIALECT_EMPTY_CLASS,
    DIALECT_EMPTY_NEGATED_CLASS,
    DIALECT_ESCAPES,
    DIALECT_OPEN_LOWER_BOUND,
    DIALECT_POSIX_CLASS,
    DIALECT_POSSESSIVE_SUFFIX,
    PORTABLE_GROUP_OPENERS,
    FieldPatternError,
)
from cmdb.framework.object_field_value_rules import anchor_field_regex
from cmdb.models.type_model.field_key_enum import FieldKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['field_pattern_problem', 'find_dialect_construct', 'find_field_pattern_errors']

# A bounded quantifier at the scanner's position: {m}, {m,}, {m,n}
_BOUNDED_QUANTIFIER: re.Pattern[str] = re.compile(r'\{\d+(?:,\d*)?\}')
# The open lower bound only the server reads as a quantifier: {,n}
_OPEN_LOWER_BOUND: re.Pattern[str] = re.compile(r'\{,\d+\}')


def _group_opener_construct(pattern: str, index: int) -> str | None:
    """
    Judges the '(?' group at ``index``: non-capturing, lookaround and named groups pass

    Args:
        pattern (str): The pattern
        index (int): The position of the '('

    Returns:
        str | None: The refused opener (e.g. '(?i', '(?P', '(?#', '(?>'), or None
    """
    rest: str = pattern[index + 2:]

    if rest.startswith(PORTABLE_GROUP_OPENERS):
        return None

    if rest.startswith('<') and len(rest) > 1 and (rest[1].isalpha() or rest[1] == '_'):
        return None

    return pattern[index:index + 3]


def _escape_construct(pattern: str, index: int) -> str | None:
    """
    Judges the escape at ``index``

    Args:
        pattern (str): The pattern
        index (int): The position of the backslash

    Returns:
        str | None: The refused escape (e.g. '\\p', '\\u{'), or None
    """
    escaped: str = pattern[index + 1:index + 2]

    if escaped in DIALECT_ESCAPES:
        return f'\\{escaped}'

    if pattern.startswith(DIALECT_CODE_POINT_ESCAPE, index):
        return DIALECT_CODE_POINT_ESCAPE

    return None


def _class_end(pattern: str, index: int) -> tuple[int, str | None]:
    """
    Walks the character class opened at ``index`` to its closing ']'

    Args:
        pattern (str): The pattern
        index (int): The position of the '['

    Returns:
        tuple[int, str | None]: The position after the class (the end of the pattern when it never closes), and
            the refused construct inside it, if any
    """
    body: int = index + 2 if pattern.startswith('[^', index) else index + 1

    if pattern[body:body + 1] == ']':
        return body + 1, DIALECT_EMPTY_NEGATED_CLASS if body == index + 2 else DIALECT_EMPTY_CLASS

    position: int = body

    while position < len(pattern):
        character: str = pattern[position]

        if character == '\\':
            if construct := _escape_construct(pattern, position):
                return position, construct
            position += 2
            continue

        if pattern.startswith(DIALECT_POSIX_CLASS, position):
            return position, DIALECT_POSIX_CLASS

        if character == ']':
            return position + 1, None

        position += 1

    return position, None


def find_dialect_construct(pattern: str) -> str | None:
    """
    Finds the first construct of a field pattern that the browser and the server read differently

    Walks the pattern once, outside and inside character classes, honouring escapes - so an escaped '\\(' or '\\{'
    is never mistaken for a group or a quantifier

    Args:
        pattern (str): The field's declared pattern

    Returns:
        str | None: The construct as the refusal names it, or None when the pattern uses none
    """
    position: int = 0
    after_quantifier: bool = False

    while position < len(pattern):
        character: str = pattern[position]
        quantified: bool = after_quantifier
        after_quantifier = False

        if character == '\\':
            if construct := _escape_construct(pattern, position):
                return construct
            position += 2
            continue

        if character == '[':
            position, construct = _class_end(pattern, position)
            if construct:
                return construct
            continue

        if character == '(' and pattern.startswith('(?', position):
            if construct := _group_opener_construct(pattern, position):
                return construct
            position += 2
            continue

        if character == '{':
            if _OPEN_LOWER_BOUND.match(pattern, position):
                return DIALECT_OPEN_LOWER_BOUND
            if bounded := _BOUNDED_QUANTIFIER.match(pattern, position):
                position, after_quantifier = bounded.end(), True
                continue

        if quantified and character == DIALECT_POSSESSIVE_SUFFIX:
            return f'{pattern[position - 1]}{DIALECT_POSSESSIVE_SUFFIX}'

        # '?' right after a quantifier makes it lazy - both dialects read that, and it quantifies nothing more
        after_quantifier = character in '*+' or (character == '?' and not quantified)
        position += 1

    return None


def field_pattern_problem(field_name: Any, regex: Any) -> str | None:
    """
    Answers why a field's declared pattern may not be written, if it may not

    Args:
        field_name (Any): The field's name, for the message
        regex (Any): The field's declared ``regex``; None or '' declares no pattern

    Returns:
        str | None: The refusal message (``FieldPatternError``), or None for a usable pattern or none at all
    """
    if regex is None or regex == '':
        return None

    if not isinstance(regex, str):
        return FieldPatternError.NOT_A_STRING.format(field=field_name, kind=type(regex).__name__)

    if construct := find_dialect_construct(regex):
        return FieldPatternError.DIALECT.format(field=field_name, construct=construct)

    try:
        regex_engine.compile(anchor_field_regex(regex))
    except regex_engine.error as err:
        return FieldPatternError.NOT_COMPILABLE.format(field=field_name, detail=err)

    return None


def find_field_pattern_errors(
        fields: Any,
        stored_fields: Any = None) -> list[str]:
    """
    Judges the pattern of every field a write declares - the ones it adds or changes

    A field whose pattern is exactly what the stored field of the same name already carries is not judged: a type
    or template whose stored pattern breaks the rule stays saveable as long as nobody touches that pattern

    Args:
        fields (Any): The written field definitions (a flat ``fields`` list)
        stored_fields (Any): The stored definitions on an update; None on a create, which judges every pattern

    Returns:
        list[str]: One message per refused pattern, in field order; empty when every pattern passes
    """
    stored: dict[Any, Any] = {
        field.get(FieldKey.NAME.value): field.get(FieldKey.REGEX.value)
        for field in stored_fields or [] if isinstance(field, dict)
    }
    errors: list[str] = []

    for field in fields if isinstance(fields, list) else []:
        if not isinstance(field, dict):
            continue

        name: Any = field.get(FieldKey.NAME.value)
        regex: Any = field.get(FieldKey.REGEX.value)

        if name in stored and stored[name] == regex:
            continue

        if problem := field_pattern_problem(name, regex):
            errors.append(problem)

    return errors

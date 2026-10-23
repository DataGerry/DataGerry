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
The two schemas of a best-practice model's ``meta`` section

Every key is required and none other is allowed in both: the section is written by hand, so a misspelt key is refused
rather than silently ignored.

    strict      a best-practice model's: every text non-blank, ``order`` a whole number of 0 or more
    exported    every transfer file's: an export writes the section with empty values (texts empty, ``order`` null),
                so only the kind of each value is held - an ordinary import never reads it
"""
from typing import Any, Callable

from cmdb.framework.configuration_transfer.best_practice_constants import BestPracticeMetaKey
# -------------------------------------------------------------------------------------------------------------------- #

# Error text when 'order' is a boolean, which cerberus would accept as an integer
ORDER_NOT_A_NUMBER: str = 'must be a whole number, not a boolean'

# A text holding at least one character that is not whitespace - over several lines too
NON_BLANK_PATTERN: str = r'(?s).*\S.*'


def reject_boolean(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Refuses a boolean where the schema asks for an integer - cerberus counts True and False as integers

    Args:
        field (str): The field being checked
        value (Any): Its value
        error (Callable[[str, str], None]): The validator's error callback
    """
    if isinstance(value, bool):
        error(field, ORDER_NOT_A_NUMBER)


def _string(strict: bool) -> dict[str, Any]:
    """
    The rule of one string - non-blank when strict

    Args:
        strict (bool): Whether the string must hold more than whitespace

    Returns:
        dict[str, Any]: The cerberus rule
    """
    if strict:
        return {'type': 'string', 'empty': False, 'regex': NON_BLANK_PATTERN}

    return {'type': 'string'}


def _text(strict: bool) -> dict[str, Any]:
    """
    The rule of one required text

    Args:
        strict (bool): Whether the text must be non-blank

    Returns:
        dict[str, Any]: The cerberus rule
    """
    return {**_string(strict), 'required': True}


def _text_list(strict: bool) -> dict[str, Any]:
    """
    The rule of a required list of texts (it may be empty)

    Args:
        strict (bool): Whether each text must be non-blank

    Returns:
        dict[str, Any]: The cerberus rule
    """
    return {'type': 'list', 'required': True, 'schema': _string(strict)}


def _build_meta_schema(strict: bool) -> dict[str, Any]:
    """
    The cerberus schema of a ``meta`` section, one rule per ``BestPracticeMetaKey``

    Args:
        strict (bool): True for a best-practice model's section, False for an exported one

    Returns:
        dict[str, Any]: The schema
    """
    category_names: dict[str, Any] = {'type': 'string', 'empty': False} if strict else {'type': 'string'}

    return {
        BestPracticeMetaKey.TITLE.value: _text(strict),
        BestPracticeMetaKey.BADGE.value: _text(strict),
        BestPracticeMetaKey.SUMMARY.value: _text(strict),
        BestPracticeMetaKey.DESCRIPTION.value: _text(strict),
        BestPracticeMetaKey.SUITED_FOR.value: _text_list(strict),
        BestPracticeMetaKey.PROFILES.value: _text_list(strict),
        BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: {
            'type': 'dict',
            'required': True,
            'keysrules': category_names,
            'valuesrules': _string(strict),
        },
        BestPracticeMetaKey.ORDER.value: {
            'type': 'integer', 'required': True, 'min': 0, 'nullable': not strict, 'check_with': reject_boolean,
        },
    }


def get_best_practice_meta_schema() -> dict[str, Any]:
    """
    The cerberus schema of a best-practice model's ``meta`` section: every value filled in

    Returns:
        dict[str, Any]: The schema, one rule per ``BestPracticeMetaKey``
    """
    return _build_meta_schema(strict=True)


def get_exported_meta_schema() -> dict[str, Any]:
    """
    The cerberus schema of any transfer file's ``meta`` section: the keys and the kind of each value, empty allowed

    Returns:
        dict[str, Any]: The schema, one rule per ``BestPracticeMetaKey``
    """
    return _build_meta_schema(strict=False)

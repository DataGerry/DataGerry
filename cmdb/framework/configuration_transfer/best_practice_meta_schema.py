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
The schema of a best-practice model's description file (``<model_id>.meta.json``)

Every key is required and none other is allowed: the file is written by hand, so a misspelt key is refused rather
than silently ignored. Every text is a non-blank string; ``order`` is a whole number of 0 or more
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


def _text() -> dict[str, Any]:
    """
    The rule of one required, non-blank text

    Returns:
        dict[str, Any]: The cerberus rule
    """
    return {'type': 'string', 'required': True, 'empty': False, 'regex': NON_BLANK_PATTERN}


def _text_list() -> dict[str, Any]:
    """
    The rule of a required list of non-blank texts (it may be empty)

    Returns:
        dict[str, Any]: The cerberus rule
    """
    return {'type': 'list', 'required': True, 'schema': {'type': 'string', 'empty': False, 'regex': NON_BLANK_PATTERN}}


def get_best_practice_meta_schema() -> dict[str, Any]:
    """
    The cerberus schema of a description file

    Returns:
        dict[str, Any]: The schema, one rule per ``BestPracticeMetaKey``
    """
    return {
        BestPracticeMetaKey.TITLE.value: _text(),
        BestPracticeMetaKey.BADGE.value: _text(),
        BestPracticeMetaKey.SUMMARY.value: _text(),
        BestPracticeMetaKey.DESCRIPTION.value: _text(),
        BestPracticeMetaKey.SUITED_FOR.value: _text_list(),
        BestPracticeMetaKey.PROFILES.value: _text_list(),
        BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value: {
            'type': 'dict',
            'required': True,
            'keysrules': {'type': 'string', 'empty': False},
            'valuesrules': {'type': 'string', 'empty': False, 'regex': NON_BLANK_PATTERN},
        },
        BestPracticeMetaKey.ORDER.value: {'type': 'integer', 'required': True, 'min': 0, 'check_with': reject_boolean},
    }

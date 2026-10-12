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
The shape a stored name must have to be found again by what a person types

A name a person types to reach something - a user's login name, a group name - is matched after the typed text
is stripped (``strip_name``), so a stored name that starts or ends with whitespace can never be reached, and a
blank one is reached by typing nothing but spaces. ``name_shape_problem`` answers why a name breaks the rule;
``check_name_shape`` is the same rule as a Cerberus ``check_with`` hook for the schemas that store such a name.

The rule: a name is not blank, does not start or end with whitespace, and holds no control character (a tab, a
line break) - whitespace inside the name is allowed
"""
import unicodedata
from typing import Any, Callable

from cmdb.utils.base_str_enum import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['CONTROL_CHARACTER_CATEGORY', 'NameShapeProblem', 'check_name_shape', 'name_shape_problem', 'strip_name']

# Unicode general category of the control characters (tab, line break, NUL, ...)
CONTROL_CHARACTER_CATEGORY: str = 'Cc'


class NameShapeProblem(BaseStrEnum):
    """
    Why a name breaks the name rule, worded as the schema error the write answers with
    """
    BLANK = 'must not be blank'
    PADDED = 'must not start or end with whitespace'
    CONTROL_CHARACTER = 'must not contain a control character (a tab or a line break)'


def strip_name(name: str) -> str:
    """
    Removes the whitespace around a name - the one spelling a typed name is matched in

    Args:
        name (str): The name as typed or stored

    Returns:
        str: The name without leading and trailing whitespace
    """
    return name.strip()


def name_shape_problem(name: str) -> NameShapeProblem | None:
    """
    Answers why a name breaks the name rule, the first problem found

    Args:
        name (str): The name to check

    Returns:
        NameShapeProblem | None: BLANK, PADDED or CONTROL_CHARACTER, in that order; None for a usable name
    """
    stripped: str = strip_name(name)

    if not stripped:
        return NameShapeProblem.BLANK

    if stripped != name:
        return NameShapeProblem.PADDED

    if any(unicodedata.category(character) == CONTROL_CHARACTER_CATEGORY for character in name):
        return NameShapeProblem.CONTROL_CHARACTER

    return None


def check_name_shape(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Cerberus ``check_with`` rule holding a name to the name rule

    Args:
        field (str): The field being validated
        value (Any): Its value; a value that is no string is the type rule's to refuse
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    if not isinstance(value, str):
        return

    problem: NameShapeProblem | None = name_shape_problem(value)

    if problem:
        error(field, problem.value)

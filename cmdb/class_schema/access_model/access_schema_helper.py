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
The Cerberus rules shared by the permission data model's schemas

Each ``check_*`` function is a ``check_with`` rule: it is handed the field, its value and Cerberus' error reporter.
The model's constants are imported inside each function, never at module level (see the class_schema package
docstring)
"""
from typing import Any, Callable

from cmdb.class_schema.id_schema_helper import MIN_PUBLIC_ID, check_unique_ids
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'check_not_blank',
    'check_unique_values',
    'check_not_reserved_field_class',
    'check_role_types',
    'check_scope_type',
    'get_description_rule',
    'get_field_class_name_rule',
]


def check_not_blank(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Refuses a string holding nothing but whitespace - the type rule refuses anything that is no string

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import NOT_BLANK_MSG

    if isinstance(value, str) and not value.strip():
        error(field, NOT_BLANK_MSG)


def check_unique_values(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Refuses a list naming one value twice; only hashable items are compared, a wrong item is the item rule's

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import VALUES_NOT_UNIQUE_MSG

    if not isinstance(value, list):
        return

    seen: set[str] = set()
    repeated: set[str] = set()

    for item in value:
        if isinstance(item, str):
            (repeated if item in seen else seen).add(item)

    if repeated:
        error(field, VALUES_NOT_UNIQUE_MSG.format(values=sorted(repeated)))


def check_not_reserved_field_class(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Refuses the name of the built-in field class - it is a code constant no stored class or role may name

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import RESERVED_FIELD_CLASS_MSG, SYSTEM_FIELD_CLASS

    if value == SYSTEM_FIELD_CLASS:
        error(field, RESERVED_FIELD_CLASS_MSG.format(name=SYSTEM_FIELD_CLASS))


def check_role_types(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Accepts a scope role's Types: every Type (``ALL_TYPES``) or a list of unique Type ids, empty included

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import (
        ALL_TYPES,
        MAX_ROLE_TYPES,
        ROLE_TYPES_SHAPE_MSG,
        ROLE_TYPES_TOO_MANY_MSG,
    )

    if value == ALL_TYPES:
        return

    is_id_list: bool = isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) and item >= MIN_PUBLIC_ID for item in value
    )

    if not is_id_list:
        error(field, ROLE_TYPES_SHAPE_MSG.format(all_types=ALL_TYPES))
        return

    if len(value) > MAX_ROLE_TYPES:
        error(field, ROLE_TYPES_TOO_MANY_MSG.format(limit=MAX_ROLE_TYPES))
        return

    check_unique_ids(field, value, error)


def check_scope_type(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Accepts the unconditional scope or a list - what the conditions in it say is the assignment payload's to judge
    against the role's Types (phase 9, R29)

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import SCOPE_SHAPE_MSG, UNCONDITIONAL_SCOPE

    if value != UNCONDITIONAL_SCOPE and not isinstance(value, list):
        error(field, SCOPE_SHAPE_MSG.format(unconditional=UNCONDITIONAL_SCOPE))


def get_description_rule() -> dict[str, Any]:
    """
    Builds the rule of an optional free-text description, empty by default - a new dict on every call

    Returns:
        dict[str, Any]: The Cerberus rule
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import DESCRIPTION_MAX_LENGTH

    return {'type': 'string', 'required': False, 'default': '', 'maxlength': DESCRIPTION_MAX_LENGTH}


def get_field_class_name_rule() -> dict[str, Any]:
    """
    Builds the rule of a field class name - a stored class's identifier and each class a scope role grants: a slug,
    never the built-in class. A new dict on every call

    Returns:
        dict[str, Any]: The Cerberus rule
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.access_model.access_constants import FIELD_CLASS_NAME_PATTERN

    return {'type': 'string', 'regex': FIELD_CLASS_NAME_PATTERN, 'check_with': check_not_reserved_field_class}

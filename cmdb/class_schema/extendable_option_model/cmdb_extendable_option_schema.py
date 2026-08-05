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
Validation schema for CmdbExtendableOption

A CmdbExtendableOption is a single selectable value belonging to an OptionType
(collection ``framework.extendableOptions``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbExtendableOption.SCHEMA.
"""
from typing import Any

from cmdb.models.extendable_option_model.option_type_enum import OptionType
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_extendable_option_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbExtendableOption document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbExtendableOption.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbExtendableOption
            'type': 'integer',
            'min': 1,
        },
        'value': {  # The option value text shown to / selectable by users
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'option_type': {  # Which OptionType this value belongs to (must be a defined OptionType value)
            'type': 'string',
            'required': True,
            'empty': False,
            'allowed': [option_type.value for option_type in OptionType],
        },
        'predefined': {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'required': True,
            'empty': False,
        },
    }

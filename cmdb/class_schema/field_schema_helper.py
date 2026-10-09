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
The rules a field definition shares wherever fields are declared

A CmdbType and a CmdbRelation both declare their fields in a flat ``fields`` list of the same shape. The keys that
describe how a field is presented and filled - its rows, description, regex, placeholder, default ``value``, helper
text and the options of a choice field - are held to the same rules in both, so they are declared here once and each
schema adds the keys it rules differently (``type``, ``name``, ``label``) and the ones only it has
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['get_field_definition_rules']


def get_field_definition_rules() -> dict[str, Any]:
    """
    Builds the Cerberus rules of the field-definition keys a CmdbType and a CmdbRelation share

    A new dict on every call, so a schema that adds to it never changes the other's

    Returns:
        dict[str, Any]: Field-definition key to Cerberus rule, to be merged into a ``fields`` entry's schema
    """
    return {
        'rows': {  # Number of rows for a TextArea field
            'type': 'integer',
            'required': False,
        },
        'description': {  # Description of the field
            'type': 'string',
            'required': False,
        },
        'regex': {  # Regex the field's value has to match
            'type': 'string',
            'required': False,
        },
        'placeholder': {  # Placeholder of the field
            'type': 'string',
            'required': False,
        },
        'value': {  # The default value of the field
            'required': False,
            'nullable': True,
        },
        'helperText': {  # Helper text of the field
            'type': 'string',
            'required': False,
        },
        'options': {  # Options of a radio or select field
            'type': 'list',
            'empty': True,
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'name': {  # Name of the option (not visible to the user)
                        'type': 'string',
                        'required': True,
                    },
                    'label': {  # Value of the option (visible to the user)
                        'type': 'string',
                        'required': True,
                    },
                },
            },
        },
    }

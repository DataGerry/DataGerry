# DATAGERRY - OpenSource Enterprise CMDB
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
Validation schema for CmdbPerson

A CmdbPerson represents a person record in DataGerry (collection ``management.person``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbPerson.SCHEMA.

The optional keys are ``nullable`` on purpose. A client that has no value for one may send null - the
Angular person form does exactly that for ``email`` - and refusing it would answer 400 for a payload
that says nothing wrong. What is never *stored* is null: ``CmdbPerson.__init__`` coerces null to the
empty string / empty list, so the document a GET returns can always be sent straight back
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_person_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPerson document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPerson.SCHEMA
    """
    # Imported inside the builder: the key enum lives in the model layer, which imports this module
    # pylint: disable=import-outside-toplevel
    from cmdb.models.person_model.person_constants import PersonKey

    return {
        PersonKey.PUBLIC_ID.value: {  # public_id of the CmdbPerson
            'type': 'integer',
            'min': 1,
        },
        PersonKey.DISPLAY_NAME.value: {  # Displayed name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PersonKey.FIRST_NAME.value: {  # First name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PersonKey.LAST_NAME.value: {  # Last name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PersonKey.PHONE_NUMBER.value: {  # Optional phone number; null is accepted and stored as ''
            'type': 'string',
            'nullable': True,
        },
        PersonKey.EMAIL.value: {  # Optional email; validated against an email pattern when non-empty
            'type': 'string',
            'required': False,
            'empty': True,
            'nullable': True,
            'regex': r'^(?!.*\.\.)[\w\.-]+@[a-zA-Z\d-]+(\.[a-zA-Z]{2,})+$',  # Email regex pattern
        },
        PersonKey.GROUPS.value: {  # public_ids of the CmdbPersonGroups this Person is assigned to
            'type': 'list',
            'nullable': True,
            'schema': {
                'type': 'integer',
                'min': 1,
            },
        },
    }

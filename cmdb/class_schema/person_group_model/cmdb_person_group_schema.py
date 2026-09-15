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
Validation schema for CmdbPersonGroup

A CmdbPersonGroup groups CmdbPersons (collection ``management.personGroup``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbPersonGroup.SCHEMA.

``email`` is required but may be empty, which is the one place this schema differs from its person
counterpart: a group is a contact address as much as a set of people, so the key is always carried,
even when blank. The optional keys are ``nullable`` for the same reason they are on CmdbPerson - a
client may say "no value" with null, while ``CmdbPersonGroup.__init__`` makes sure null is never
stored
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_person_group_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPersonGroup document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPersonGroup.SCHEMA
    """
    # Imported inside the builder: the key enum lives in the model layer, which imports this module
    # pylint: disable=import-outside-toplevel
    from cmdb.models.person_group_model.person_group_constants import PersonGroupKey

    return {
        PersonGroupKey.PUBLIC_ID.value: {  # public_id of the CmdbPersonGroup
            'type': 'integer',
            'min': 1,
        },
        PersonGroupKey.NAME.value: {  # Name of the person group
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PersonGroupKey.EMAIL.value: {  # Contact email for the group; required, may be empty or null
            'type': 'string',
            'required': True,
            'empty': True,
            'nullable': True,
            'regex': r'^(?!.*\.\.)[\w\.-]+@[a-zA-Z\d-]+(\.[a-zA-Z]{2,})+$',  # Email regex pattern
        },
        PersonGroupKey.GROUP_MEMBERS.value: {  # public_ids of the CmdbPersons that belong to this group
            'type': 'list',
            'nullable': True,
            'schema': {
                'type': 'integer',
                'min': 1,
            },
        },
    }

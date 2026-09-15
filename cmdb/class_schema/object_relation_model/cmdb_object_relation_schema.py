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
Validation schema for CmdbObjectRelation

A CmdbObjectRelation is a concrete relation instance between two CmdbObjects
(collection ``framework.objectRelations``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbObjectRelation.SCHEMA.

The keys come from ``ObjectRelationKey``, so the schema and the model cannot drift apart on a key name.

Both timestamps accept the three shapes a date arrives in and are normalised to a real datetime before
the document is stored (``CmdbObjectRelation.DATE_FIELDS``). They are **server-owned** either way: the
create route stamps ``creation_time`` and clears ``last_edit_time``, and the update route preserves the
first and stamps the second, so a value sent for either is validated and then overwritten
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# The three shapes a date arrives in: the Mongo extended-JSON wrapper {'$date': ...} the frontend
# sends, a timestamp string from an API client, and a real datetime (an already-normalised payload)
_DATE_TYPES: list[str] = ['dict', 'string', 'datetime']

# pylint: disable=R0801
def get_cmdb_object_relation_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbObjectRelation document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbObjectRelation.SCHEMA
    """
    # Imported inside the builder: the key enum lives in the model layer, which imports this module
    # pylint: disable=import-outside-toplevel
    from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationKey

    return {
        ObjectRelationKey.PUBLIC_ID.value: {  # public_id of CmdbObjectRelation
            'type': 'integer'
        },
        ObjectRelationKey.RELATION_ID.value: {  # public_id of the CmdbRelation
            'type': 'integer',
            'required': True,
            'empty': False
        },
        ObjectRelationKey.CREATION_TIME.value: {  # Stamped on create, preserved by every update
            'anyof_type': _DATE_TYPES,
            'nullable': True,
            'required': False
        },
        ObjectRelationKey.LAST_EDIT_TIME.value: {  # Null until the first edit, stamped by the update
            'anyof_type': _DATE_TYPES,
            'nullable': True,
            'required': False
        },
        ObjectRelationKey.AUTHOR_ID.value: {  # The CmdbUser who created it, then the last one editing it
            'type': 'integer'
        },
        ObjectRelationKey.RELATION_PARENT_ID.value: {  # public_id of the parent CmdbObject
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: {  # public_id of the parent CmdbType
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        ObjectRelationKey.RELATION_CHILD_ID.value: {  # public_id of the child CmdbObject
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        ObjectRelationKey.RELATION_CHILD_TYPE_ID.value: {  # public_id of the child CmdbType
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        ObjectRelationKey.FIELD_VALUES.value: {  # Name/value pairs, not the triples an object carries
            'type': 'list',
            'required': False,
            'default': [],
        }
    }

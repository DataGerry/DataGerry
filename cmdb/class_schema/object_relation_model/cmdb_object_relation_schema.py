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
Validation schema for CmdbObjectRelation

A CmdbObjectRelation is a concrete relation instance between two CmdbObjects
(collection ``framework.objectRelations``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbObjectRelation.SCHEMA.
"""
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_object_relation_schema() -> dict:
    """
    Builds the Cerberus validation schema for a CmdbObjectRelation document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbObjectRelation.SCHEMA
    """
    return {
        'public_id': {  # public_id of CmdbObjectRelation
            'type': 'integer'
        },
        'relation_id': {  # public_id of the CmdbRelation
            'type': 'integer',
            'required': True,
            'empty': False
        },
        'creation_time': {  # When the CmdbObjectRelation was created
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'last_edit_time': {  # When the CmdbObjectRelation was last time edited
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'author_id': {  # public_id of the CmdbUser who created the CmdbObjectRelation then the last one editing it
            'type': 'integer'
        },
        'relation_parent_id': {  # public_id of the parent CmdbObject
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        'relation_parent_type_id': {  # public_id of the parent CmdbType
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        'relation_child_id': {  # public_id of the child CmdbObject
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        'relation_child_type_id': {  # public_id of the child CmdbType
            'type': 'integer',
            'nullable': False,
            'required': True,
            'empty': False
        },
        'field_values': {  # All field values for this CmdbObjectRelation
            'type': 'list',
            'required': False,
            'default': [],
        }
    }

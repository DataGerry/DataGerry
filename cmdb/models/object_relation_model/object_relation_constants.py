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
Shared constants for CmdbObjectRelations

The document keys, the role an object plays in a relation instance and the relation-tab descriptor
keys live here because all three layers need the same values: the routes read them off a request body,
the ObjectRelationsManager queries and aggregates on them, and the ObjectRelationLogsManager diffs on
them. They belong to the document, not to any one of those layers, so they are declared next to the
model instead of being repeated per layer
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ObjectRelationKey',
    'ObjectRelationFieldValueKey',
    'ObjectRelationRole',
    'RelationTabKey',
]


class ObjectRelationKey(BaseStrEnum):
    """Document field names of a CmdbObjectRelation (collection ``framework.objectRelations``)"""
    PUBLIC_ID = 'public_id'
    RELATION_ID = 'relation_id'
    RELATION_PARENT_ID = 'relation_parent_id'
    RELATION_PARENT_TYPE_ID = 'relation_parent_type_id'
    RELATION_CHILD_ID = 'relation_child_id'
    RELATION_CHILD_TYPE_ID = 'relation_child_type_id'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'
    FIELD_VALUES = 'field_values'


class ObjectRelationFieldValueKey(BaseStrEnum):
    """
    Keys of a single ``field_values`` entry

    An object-relation field value is a ``name``/``value`` pair by design (consumed that way across
    the codebase); it is intentionally NOT a name/value/type triple like a CmdbObject field
    """
    NAME = 'name'
    VALUE = 'value'


class ObjectRelationRole(BaseStrEnum):
    """
    Side an object plays in a relation instance

    A self-relation places the same object on both sides, so an object can hold both roles for one
    relation definition
    """
    PARENT = 'parent'
    CHILD = 'child'


class RelationTabKey(BaseStrEnum):
    """Keys of a single relation-tab descriptor (one per relation definition and role)"""
    RELATION_ID = 'relation_id'
    ROLE = 'role'
    LABEL = 'label'
    ICON = 'icon'
    COLOR = 'color'
    COUNT = 'count'

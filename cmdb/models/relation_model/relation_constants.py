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
Shared constants for CmdbRelations

The document keys live here because every layer needs the same values: the routes read them off a
request body, the RelationsManager queries and cascades on them, the ObjectRelationsManager projects
the role-oriented display fields of a relation definition into a relation tab, and the model
serialises them. They belong to the document, not to any one of those layers, so they are declared
next to the model instead of being repeated per layer.

``RelationDiffKey`` names the keys of the section/field diff that travels from the relation update to
the dependent CmdbObjectRelations - it is a route-to-manager contract rather than a stored document,
but it is produced and consumed in two different layers, so it belongs here for the same reason.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RelationKey',
    'RelationDiffKey',
]


class RelationKey(BaseStrEnum):
    """Document field names of a CmdbRelation (collection ``framework.relations``)"""
    PUBLIC_ID = 'public_id'
    RELATION_NAME = 'relation_name'
    DESCRIPTION = 'description'
    PARENT_TYPE_IDS = 'parent_type_ids'
    CHILD_TYPE_IDS = 'child_type_ids'
    RELATION_NAME_PARENT = 'relation_name_parent'
    RELATION_NAME_CHILD = 'relation_name_child'
    RELATION_ICON_PARENT = 'relation_icon_parent'
    RELATION_ICON_CHILD = 'relation_icon_child'
    RELATION_COLOR_PARENT = 'relation_color_parent'
    RELATION_COLOR_CHILD = 'relation_color_child'
    SECTIONS = 'sections'
    FIELDS = 'fields'


class RelationDiffKey(BaseStrEnum):
    """
    Keys of the ``changed_fields`` diff of a CmdbRelation update

    Produced by ``get_added_and_removed_fields`` and consumed by
    ``ObjectRelationsManager.update_changed_fields``, which adds / removes the named field values on
    every dependent CmdbObjectRelation
    """
    ADDED = 'added'
    REMOVED = 'removed'

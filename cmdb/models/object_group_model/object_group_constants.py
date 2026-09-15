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
Document keys of a CmdbObjectGroup

The keys of the ``framework.objectGroups`` documents, named once - they were spelled out as bare
literals in the model's ``from_data``, its ``to_json`` and the Cerberus schema.

``OBJECT_GROUP_LIST_KEYS`` names the keys the model coerces to the empty list instead of storing null.
``assigned_ids`` is deliberately NOT one of them: the schema requires it to be a non-empty list, so
filling it in would turn a document that lost the key into a group of nothing - a state the schema
itself refuses - instead of refusing to read it

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ObjectGroupKey',
    'OBJECT_GROUP_LIST_KEYS',
]


class ObjectGroupKey(BaseStrEnum):
    """
    Field keys of a CmdbObjectGroup document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    GROUP_TYPE = 'group_type'
    ASSIGNED_IDS = 'assigned_ids'
    CATEGORIES = 'categories'


# The list-valued keys: absent or null becomes the empty list, never null. 'assigned_ids' is required
# and non-empty, so it is not here - see the module docstring
OBJECT_GROUP_LIST_KEYS: tuple[str, ...] = (
    ObjectGroupKey.CATEGORIES.value,
)

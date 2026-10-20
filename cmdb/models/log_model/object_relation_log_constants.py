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
Document keys of a CmdbObjectRelationLog

The keys of the ``framework.objectRelationLogs`` documents, named once. They were spelled out three
times for nine keys - the model's ``from_data``, its ``to_json``, and the log builder in
``ObjectRelationLogsManager``, which assembles the document from bare literals - and there is no
Cerberus schema to catch a typo, because nothing outside the backend ever writes one of these.

``OBJECT_RELATION_LOG_DATE_KEYS`` is read as the model's ``DATE_FIELDS``, so a timestamp is a real date
however the document was built

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ObjectRelationLogKey',
    'OBJECT_RELATION_LOG_DATE_KEYS',
]


class ObjectRelationLogKey(BaseStrEnum):
    """Field keys of a CmdbObjectRelationLog document"""
    PUBLIC_ID = 'public_id'
    OBJECT_RELATION_ID = 'object_relation_id'
    OBJECT_RELATION_PARENT_ID = 'object_relation_parent_id'
    OBJECT_RELATION_CHILD_ID = 'object_relation_child_id'
    CREATION_TIME = 'creation_time'
    ACTION = 'action'
    AUTHOR_ID = 'author_id'
    AUTHOR_NAME = 'author_name'
    CHANGES = 'changes'


# The keys holding a timestamp, read as CmdbObjectRelationLog's DATE_FIELDS
OBJECT_RELATION_LOG_DATE_KEYS: tuple[ObjectRelationLogKey, ...] = (
    ObjectRelationLogKey.CREATION_TIME,
)

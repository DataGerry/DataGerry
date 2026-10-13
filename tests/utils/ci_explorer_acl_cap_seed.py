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
The seed of the CI Explorer cap-and-ACL tests: neighbours the caller may not read sort ahead of a readable one

* OPEN_TYPE_ID (no ACL) and LOCKED_TYPE_ID (an activated ACL naming no group: it denies every group, the suite's
  admin included)
* FOCAL_ID relates to the two HIDDEN_IDS (locked, the lowest ids) and to READABLE_ID
* LOCATION_FOCAL_ID has a location node with the two LOCATION_HIDDEN_CHILD_IDS (locked, lowest) and
  LOCATION_READABLE_CHILD_ID under it, and no relations - nothing else spends its budget
* HIDDEN_FOCAL_ID is itself of the locked type

Everything is written straight into the collections and removed by id
"""
from datetime import datetime, timezone
from functools import partial
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OPEN_TYPE_ID: int = 98501
LOCKED_TYPE_ID: int = 98502
FOCAL_ID: int = 98510
HIDDEN_IDS: list[int] = [98511, 98512]
READABLE_ID: int = 98513
HIDDEN_FOCAL_ID: int = 98514
LOCATION_HIDDEN_CHILD_IDS: list[int] = [98515, 98516]
LOCATION_READABLE_CHILD_ID: int = 98517
RELATION_ID: int = 98520
FIRST_OBJECT_RELATION_ID: int = 98530
READABLE_OBJECT_RELATION_ID: int = 98539
FOCAL_NODE_ID: int = 98540
READABLE_CHILD_NODE_ID: int = 98549
# The location source's focal object: it has location children and no relations, so nothing else spends its budget
LOCATION_FOCAL_ID: int = 98518
ROOT_LOCATION_ID: int = 1
ALL_OBJECT_IDS: list[int] = [FOCAL_ID, *HIDDEN_IDS, READABLE_ID, HIDDEN_FOCAL_ID, *LOCATION_HIDDEN_CHILD_IDS,
                             LOCATION_READABLE_CHILD_ID, LOCATION_FOCAL_ID]
LOCKED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {}}}


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A CmdbObject with a name"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': [{'name': 'dg-name', 'value': f'o{public_id}'}]}


def _object_relation(public_id: int, child_id: int, child_type_id: int) -> dict[str, Any]:
    """FOCAL -> child"""
    return {'public_id': public_id, 'relation_id': RELATION_ID, 'relation_parent_id': FOCAL_ID,
            'relation_parent_type_id': OPEN_TYPE_ID, 'relation_child_id': child_id,
            'relation_child_type_id': child_type_id, 'author_id': 1, 'creation_time': datetime.now(timezone.utc),
            'last_edit_time': None, 'field_values': []}


def _node(public_id: int, object_id: int, type_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation node"""
    return {'public_id': public_id, 'name': f'node-{public_id}', 'parent': parent, 'object_id': object_id,
            'type_id': type_id, 'type_label': 'Cap', 'type_icon': 'fa-cube', 'type_selectable': True}


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything ``seed`` wrote, by id"""
    collection = partial(database_manager.get_collection, db_name=database_name)

    collection(CmdbType.COLLECTION).delete_many({'public_id': {'$in': [OPEN_TYPE_ID, LOCKED_TYPE_ID]}})
    collection(CmdbObject.COLLECTION).delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    collection(CmdbRelation.COLLECTION).delete_many({'public_id': RELATION_ID})
    collection(CmdbObjectRelation.COLLECTION).delete_many({'relation_id': RELATION_ID})
    collection(CmdbLocation.COLLECTION).delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The two types, the objects, the relations and a location node with three children"""
    collection = partial(database_manager.get_collection, db_name=database_name)

    purge(database_manager, database_name)
    locked = make_type_doc(LOCKED_TYPE_ID, 'cap-locked')
    locked['acl'] = LOCKED_ACL
    collection(CmdbType.COLLECTION).insert_many([make_type_doc(OPEN_TYPE_ID, 'cap-open'), locked])
    collection(CmdbObject.COLLECTION).insert_many(
        [_object(FOCAL_ID, OPEN_TYPE_ID), _object(READABLE_ID, OPEN_TYPE_ID), _object(HIDDEN_FOCAL_ID, LOCKED_TYPE_ID),
         _object(LOCATION_READABLE_CHILD_ID, OPEN_TYPE_ID), _object(LOCATION_FOCAL_ID, OPEN_TYPE_ID)]
        + [_object(hidden, LOCKED_TYPE_ID) for hidden in HIDDEN_IDS + LOCATION_HIDDEN_CHILD_IDS]
    )
    collection(CmdbRelation.COLLECTION).insert_one({
        'public_id': RELATION_ID, 'relation_name': 'cap-linked', 'parent_type_ids': [OPEN_TYPE_ID],
        'child_type_ids': [OPEN_TYPE_ID, LOCKED_TYPE_ID], 'relation_name_parent': 'links',
        'relation_name_child': 'linked_by', 'relation_icon_parent': 'fa-arrow-right',
        'relation_icon_child': 'fa-arrow-left', 'relation_color_parent': '#33aa33',
        'relation_color_child': '#aa3333', 'description': '', 'sections': [], 'fields': [],
    })
    collection(CmdbObjectRelation.COLLECTION).insert_many([
        _object_relation(FIRST_OBJECT_RELATION_ID + index, child, LOCKED_TYPE_ID)
        for index, child in enumerate(HIDDEN_IDS)
    ] + [_object_relation(READABLE_OBJECT_RELATION_ID, READABLE_ID, OPEN_TYPE_ID)])
    collection(CmdbLocation.COLLECTION).insert_many(
        [_node(FOCAL_NODE_ID, LOCATION_FOCAL_ID, OPEN_TYPE_ID, ROOT_LOCATION_ID)]
        + [_node(FOCAL_NODE_ID + 1 + index, child, LOCKED_TYPE_ID, FOCAL_NODE_ID)
           for index, child in enumerate(LOCATION_HIDDEN_CHILD_IDS)]
        + [_node(READABLE_CHILD_NODE_ID, LOCATION_READABLE_CHILD_ID, OPEN_TYPE_ID, FOCAL_NODE_ID)]
    )

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
The seed of the CmdbLocation write tests: objects a location node can be written for, under every rule
the write routes apply

* VISIBLE and HIDDEN types - both with a location field and a summary on their name field; only the
  admin group may read HIDDEN
* PLAIN type - no location field, so its objects can never sit in the tree
* SUMMARY_REF type - a summary naming a reference field, to compare a render with and without reference
  expansion; and its summary also names the location field, to see what a move does to a derived name
* a node that is not selectable as a parent
* a LOCATION_EDITOR - a group holding the location rights alone, reading neither HIDDEN's objects nor
  anything else the ACL grants the admin group only

Everything is written straight into the collections
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import LocationRight
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

VISIBLE_TYPE_ID: int = 89501
HIDDEN_TYPE_ID: int = 89502
PLAIN_TYPE_ID: int = 89503
SUMMARY_REF_TYPE_ID: int = 89504
MISSING_TYPE_ID: int = 89509

VISIBLE_ID: int = 89511
HIDDEN_ID: int = 89512
PLAIN_ID: int = 89513
SUMMARY_REF_ID: int = 89514
ORPHAN_ID: int = 89515
MISSING_OBJECT_ID: int = 89519

PARENT_NODE_ID: int = 89521
PARENT_NODE_OBJECT_ID: int = 89531
UNSELECTABLE_NODE_ID: int = 89522
UNSELECTABLE_NODE_OBJECT_ID: int = 89532
HIDDEN_NODE_ID: int = 89523
VISIBLE_NODE_ID: int = 89524
SUMMARY_REF_NODE_ID: int = 89525

EDITOR_GROUP_ID: int = 89541
EDITOR_ID: int = 89542
EDITOR_NAME: str = 'location-write-editor'

NAME_FIELD: str = 'dg_name'
LOCATION_FIELD: str = 'placement'
REF_FIELD: str = 'points-at'

VISIBLE_VALUE: str = 'visible-location-value'
HIDDEN_VALUE: str = 'hidden-location-value'
PLAIN_VALUE: str = 'plain-location-value'
SUMMARY_REF_VALUE: str = 'summary-ref-value'
STORED_NODE_NAME: str = 'stored-node-name'

ALL_TYPE_IDS: list[int] = [VISIBLE_TYPE_ID, HIDDEN_TYPE_ID, PLAIN_TYPE_ID, SUMMARY_REF_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [VISIBLE_ID, HIDDEN_ID, PLAIN_ID, SUMMARY_REF_ID, ORPHAN_ID]
ALL_NODE_IDS: list[int] = [PARENT_NODE_ID, UNSELECTABLE_NODE_ID, HIDDEN_NODE_ID, VISIBLE_NODE_ID, SUMMARY_REF_NODE_ID]


def type_label(type_id: int) -> str:
    """The label every seeded type carries - and every node written for one of its objects."""
    return f'Location Write {type_id}'


def _type_doc(public_id: int, with_location: bool = True, summary: list[str] | None = None,
              extra_fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A type with a name field, optionally a location field, whose summary names `summary`."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}]

    if with_location:
        fields.append({'type': FieldType.LOCATION.value, 'name': LOCATION_FIELD, 'label': 'Location'})

    fields += extra_fields or []

    return {
        'public_id': public_id, 'name': f'location-write-{public_id}', 'label': type_label(public_id),
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'selectable_as_parent': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
                          'fields': [field['name'] for field in fields]}],
            'summary': {'fields': summary or [NAME_FIELD]},
            'externals': [],
        },
        'acl': {'activated': False, 'groups': {'includes': {}}}, 'version': '1.0.0',
    }


def _object_doc(public_id: int, type_id: int, value: str, with_location: bool = True,
                extra_fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An object of `type_id` named `value`, not yet placed."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': value}]

    if with_location:
        fields.append({'type': FieldType.LOCATION.value, 'name': LOCATION_FIELD, 'value': None})

    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': fields + (extra_fields or []),
        'multi_data_sections': [],
    }


def node_doc(public_id: int, object_id: int, parent: int, type_id: int = VISIBLE_TYPE_ID,
             selectable: bool = True, name: str = STORED_NODE_NAME) -> dict[str, Any]:
    """A complete CmdbLocation document."""
    return {
        'public_id': public_id, 'name': name, 'parent': parent, 'object_id': object_id, 'type_id': type_id,
        'type_label': type_label(type_id), 'type_icon': 'fa-cube', 'type_selectable': selectable,
    }


def seed(database_manager: MongoDatabaseManager, database_name: str, root_id: int) -> None:
    """Writes the types, the objects, the two parent nodes under `root_id`, the editor group and user."""
    purge(database_manager, database_name)
    reference_field: dict[str, Any] = {'type': FieldType.REFERENCE.value, 'name': REF_FIELD, 'label': 'Ref',
                                       'ref_types': [VISIBLE_TYPE_ID]}
    hidden: dict[str, Any] = _type_doc(HIDDEN_TYPE_ID)
    hidden['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}

    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_many([
        _type_doc(VISIBLE_TYPE_ID), hidden, _type_doc(PLAIN_TYPE_ID, with_location=False),
        _type_doc(SUMMARY_REF_TYPE_ID, summary=[NAME_FIELD, REF_FIELD, LOCATION_FIELD],
                  extra_fields=[reference_field]),
    ])
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        _object_doc(VISIBLE_ID, VISIBLE_TYPE_ID, VISIBLE_VALUE),
        _object_doc(HIDDEN_ID, HIDDEN_TYPE_ID, HIDDEN_VALUE),
        _object_doc(PLAIN_ID, PLAIN_TYPE_ID, PLAIN_VALUE, with_location=False),
        _object_doc(SUMMARY_REF_ID, SUMMARY_REF_TYPE_ID, SUMMARY_REF_VALUE, extra_fields=[
            {'type': FieldType.REFERENCE.value, 'name': REF_FIELD, 'value': VISIBLE_ID},
        ]),
        _object_doc(ORPHAN_ID, MISSING_TYPE_ID, PLAIN_VALUE),
    ])
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_many([
        node_doc(PARENT_NODE_ID, PARENT_NODE_OBJECT_ID, root_id),
        node_doc(UNSELECTABLE_NODE_ID, UNSELECTABLE_NODE_OBJECT_ID, root_id, selectable=False),
    ])
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).insert_one({
        'public_id': EDITOR_GROUP_ID, 'name': EDITOR_NAME, 'label': EDITOR_NAME,
        'rights': [LocationRight.VIEW.value, LocationRight.ADD.value, LocationRight.EDIT.value],
    })
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': EDITOR_ID, 'user_name': EDITOR_NAME, 'active': True, 'group_id': EDITOR_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
    })


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote, and every node written for the seeded objects."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_OBJECT_IDS}})
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many({'$or': [
        {'public_id': {'$in': ALL_NODE_IDS}}, {'object_id': {'$in': ALL_OBJECT_IDS}},
    ]})
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).delete_many(
        {'public_id': EDITOR_GROUP_ID})
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_many({'public_id': EDITOR_ID})


def location_editor() -> CmdbUser:
    """The seeded member of the group holding the location rights alone."""
    return CmdbUser(public_id=EDITOR_ID, user_name=EDITOR_NAME, active=True, group_id=EDITOR_GROUP_ID)


def load(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> CmdbObject:
    """Reads one seeded object."""
    return CmdbObject.from_data(
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id}))


def stored_node(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> dict[str, Any] | None:
    """The CmdbLocation stored for `object_id`, or None."""
    return database_manager.get_collection(CmdbLocation.COLLECTION, database_name).find_one({'object_id': object_id})


def location_value(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> Any:
    """The stored value of the object's location field."""
    stored: CmdbObject = load(database_manager, database_name, object_id)

    return next(field['value'] for field in stored.fields if field['name'] == LOCATION_FIELD)

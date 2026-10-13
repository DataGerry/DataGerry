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
The seed of the rack membership ACL tests: racks and members under every rule the object ACL applies to them

* RACK - an ordinary Rack; READ_ONLY_RACK - a Rack the editor may read but not change; HIDDEN_RACK - a Rack only the
  administrators may read. Each of its own Rack type, since an ACL lives on the type
* members: OPEN (no ACL), HIDDEN (administrators only), READ_ONLY (the editor may read, not change), DEACTIVATED
  (an inactive type) - every one of a type with a location field, so only the ACL can refuse it
* EDITOR - a group holding the rack rights and the object view right, and nothing an ACL does not grant it

Everything is written straight into the collections and removed by id
"""
from datetime import datetime, timezone
from functools import partial
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackRight
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

RACK_TYPE_ID: int = 98701
READ_ONLY_RACK_TYPE_ID: int = 98702
HIDDEN_RACK_TYPE_ID: int = 98703
OPEN_TYPE_ID: int = 98704
HIDDEN_TYPE_ID: int = 98705
READ_ONLY_TYPE_ID: int = 98706
DEACTIVATED_TYPE_ID: int = 98707

RACK_ID: int = 98711
OTHER_RACK_ID: int = 98712
READ_ONLY_RACK_ID: int = 98713
HIDDEN_RACK_ID: int = 98714
OPEN_ID: int = 98721
HIDDEN_ID: int = 98722
READ_ONLY_ID: int = 98723
DEACTIVATED_ID: int = 98724
SECOND_OPEN_ID: int = 98725
MISSING_ID: int = 98799

EDITOR_GROUP_ID: int = 98741
EDITOR_ID: int = 98742
EDITOR_NAME: str = 'rack-membership-editor'

ADMIN_ALL: dict[str, list[str]] = {str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}
HIDDEN_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': ADMIN_ALL}}
READ_ONLY_ACL: dict[str, Any] = {
    'activated': True, 'groups': {'includes': ADMIN_ALL | {str(EDITOR_GROUP_ID): ['READ']}},
}
OPEN_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': None}}

RACK_HEIGHT: int = 42
NAME_FIELD: str = 'member-name'

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, READ_ONLY_RACK_TYPE_ID, HIDDEN_RACK_TYPE_ID, OPEN_TYPE_ID, HIDDEN_TYPE_ID,
                           READ_ONLY_TYPE_ID, DEACTIVATED_TYPE_ID]
ALL_RACK_IDS: list[int] = [RACK_ID, OTHER_RACK_ID, READ_ONLY_RACK_ID, HIDDEN_RACK_ID]
ALL_OBJECT_IDS: list[int] = ALL_RACK_IDS + [OPEN_ID, HIDDEN_ID, READ_ONLY_ID, DEACTIVATED_ID, SECOND_OPEN_ID]


def _rack_type(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A Rack CmdbType with the given ACL"""
    return {
        'public_id': public_id, 'name': f'rack-acl-{public_id}', 'label': 'Rack', 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True, 'version': '1.0.0', 'acl': acl,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
            {'type': 'location', 'name': RackField.LOCATION.value, 'label': 'Location'},
        ],
        'render_meta': {'icon': 'fa-server', 'summary': {'fields': [RackField.NAME.value]}, 'sections': [{
            'type': 'section', 'name': RackSection.INFORMATION.value, 'label': 'Information',
            'fields': [RackField.NAME.value, RackField.HEIGHT.value, RackField.LOCATION.value],
        }]},
    }


def _member_type(public_id: int, acl: dict[str, Any], active: bool = True) -> dict[str, Any]:
    """A mountable CmdbType (it declares a location field) with the given ACL"""
    return {
        'public_id': public_id, 'name': f'rack-acl-member-{public_id}', 'label': 'Member', 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': active, 'version': '1.0.0', 'acl': acl,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
                   {'type': 'location', 'name': RackField.LOCATION.value, 'label': 'Location'}],
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]},
    }


def _object(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A CmdbObject"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': fields}


def _rack(public_id: int, type_id: int) -> dict[str, Any]:
    """A Rack object"""
    return _object(public_id, type_id, [{'type': 'text', 'name': RackField.NAME.value, 'value': f'rack-{public_id}'},
                                        {'type': 'number', 'name': RackField.HEIGHT.value, 'value': RACK_HEIGHT}])


def _member(public_id: int, type_id: int) -> dict[str, Any]:
    """A member object"""
    return _object(public_id, type_id, [{'type': 'text', 'name': NAME_FIELD, 'value': f'member-{public_id}'}])


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The types, the racks, the members, the editor group and user"""
    collection = partial(database_manager.get_collection, db_name=database_name)
    purge(database_manager, database_name)
    collection(CmdbType.COLLECTION).insert_many([
        _rack_type(RACK_TYPE_ID, OPEN_ACL), _rack_type(READ_ONLY_RACK_TYPE_ID, READ_ONLY_ACL),
        _rack_type(HIDDEN_RACK_TYPE_ID, HIDDEN_ACL), _member_type(OPEN_TYPE_ID, OPEN_ACL),
        _member_type(HIDDEN_TYPE_ID, HIDDEN_ACL), _member_type(READ_ONLY_TYPE_ID, READ_ONLY_ACL),
        _member_type(DEACTIVATED_TYPE_ID, OPEN_ACL, active=False),
    ])
    collection(CmdbObject.COLLECTION).insert_many([
        _rack(RACK_ID, RACK_TYPE_ID), _rack(OTHER_RACK_ID, RACK_TYPE_ID),
        _rack(READ_ONLY_RACK_ID, READ_ONLY_RACK_TYPE_ID), _rack(HIDDEN_RACK_ID, HIDDEN_RACK_TYPE_ID),
        _member(OPEN_ID, OPEN_TYPE_ID), _member(SECOND_OPEN_ID, OPEN_TYPE_ID), _member(HIDDEN_ID, HIDDEN_TYPE_ID),
        _member(READ_ONLY_ID, READ_ONLY_TYPE_ID), _member(DEACTIVATED_ID, DEACTIVATED_TYPE_ID),
    ])
    collection(CmdbUserGroup.COLLECTION).insert_one({
        'public_id': EDITOR_GROUP_ID, 'name': EDITOR_NAME, 'label': EDITOR_NAME,
        'rights': [RackRight.VIEW.value, RackRight.EDIT.value, ObjectRightName.VIEW.value],
    })
    collection(CmdbUser.COLLECTION).insert_one({
        'public_id': EDITOR_ID, 'user_name': EDITOR_NAME, 'active': True, 'group_id': EDITOR_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
    })


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything seed wrote, and every mount and location node of its objects"""
    collection = partial(database_manager.get_collection, db_name=database_name)
    collection(CmdbType.COLLECTION).delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    collection(CmdbObject.COLLECTION).delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    collection(CmdbRackMount.COLLECTION).delete_many({'rack_id': {'$in': ALL_RACK_IDS}})
    collection(CmdbLocation.COLLECTION).delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})
    collection(CmdbUserGroup.COLLECTION).delete_many({'public_id': EDITOR_GROUP_ID})
    collection(CmdbUser.COLLECTION).delete_many({'public_id': EDITOR_ID})


def editor() -> CmdbUser:
    """The seeded member of the rack editor group"""
    return CmdbUser(public_id=EDITOR_ID, user_name=EDITOR_NAME, active=True, group_id=EDITOR_GROUP_ID)


def mount_of(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> dict[str, Any] | None:
    """The stored mount of an object, if any"""
    return database_manager.get_collection(CmdbRackMount.COLLECTION, database_name).find_one({'object_id': object_id})

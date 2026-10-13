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
Integration tests for the object ACL on the Rack routes, against a real MongoDB and the real managers

What the unit tests cannot show: the access rules read the ACLs MongoDB stores - an activated ACL that names only the
administrators, one granting the editor READ alone, a deactivated type - and decide each case as the routes need;
and the ruled cascade: when a Rack moves, every member follows, also the ones its mover may not change
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_UPDATE_DENIED_MSG,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_access_helper import member_access_blocker, rack_access_blocker
from cmdb.interface.rest_api.routes.rack_routes.rack_location_helper import reconcile_member_locations
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount
from cmdb.models.special_type_model.rack_constants import RackField
from tests.utils import rack_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

ROOT_LOCATION_ID: int = 1
RACK_NODE_ID: int = 98751
HIDDEN_MOUNT_ID: int = 98761


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The seed, the request context the managers resolve in, and the real objects manager"""
    seed.seed(database_manager, database_name)

    with rest_api.application.test_request_context():
        yield ObjectsManager(database_manager)

    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
        {'public_id': RACK_NODE_ID})
    seed.purge(database_manager, database_name)


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """A stored object document"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})


class TestTheMemberRule:
    """READ and UPDATE on the member's type, and an active type."""

    @pytest.mark.parametrize('object_id,expected', [
        (seed.OPEN_ID, None),
        (seed.HIDDEN_ID, LINKED_OBJECT_DENIED_MSG.format(object_id=seed.HIDDEN_ID)),
        (seed.READ_ONLY_ID, LINKED_OBJECT_UPDATE_DENIED_MSG.format(object_id=seed.READ_ONLY_ID)),
    ], ids=['open', 'hidden', 'read-only'])
    def test_each_stored_acl(self, database_manager, database_name, objects_manager: ObjectsManager,
                             object_id: int, expected: str | None) -> None:
        """What the editor may move, read, or neither"""
        member = _stored(database_manager, database_name, object_id)

        assert member_access_blocker(member, objects_manager, seed.editor()) == expected

    def test_a_deactivated_type_is_refused_for_everyone(
            self, database_manager, database_name, objects_manager: ObjectsManager) -> None:
        """Even without an ACL - no object write changes an object of an inactive type"""
        member = _stored(database_manager, database_name, seed.DEACTIVATED_ID)

        assert member_access_blocker(member, objects_manager, seed.editor()) is not None


class TestTheRackRule:
    """READ for a read, READ and UPDATE for a membership write."""

    @pytest.mark.parametrize('rack_id,read,write', [
        (seed.RACK_ID, None, None),
        (seed.READ_ONLY_RACK_ID, None,
         RackAccessError.RACK_UPDATE_DENIED.format(object_id=seed.READ_ONLY_RACK_ID)),
        (seed.HIDDEN_RACK_ID, RackAccessError.RACK_READ_DENIED.format(object_id=seed.HIDDEN_RACK_ID),
         RackAccessError.RACK_READ_DENIED.format(object_id=seed.HIDDEN_RACK_ID)),
    ], ids=['open', 'read-only', 'hidden'])
    def test_each_stored_acl(self, database_manager, database_name, objects_manager: ObjectsManager,
                             rack_id: int, read: str | None, write: str | None) -> None:
        """Both answers per Rack"""
        rack = _stored(database_manager, database_name, rack_id)

        assert rack_access_blocker(rack, objects_manager, seed.editor(), write=False) == read
        assert rack_access_blocker(rack, objects_manager, seed.editor(), write=True) == write


class TestMembersFollowTheirRack:
    """Ruled: a member's place is the Rack's once it joined - no member is asked when the Rack moves."""

    def test_a_member_the_mover_may_not_change_follows(
            self, database_manager: MongoDatabaseManager, database_name: str,
            objects_manager: ObjectsManager) -> None:
        """The hidden member gets its node under the Rack's node, though the restricted editor moved the Rack"""
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        locations.insert_one({'public_id': RACK_NODE_ID, 'name': 'rack-node', 'parent': ROOT_LOCATION_ID,
                              'object_id': seed.RACK_ID, 'type_id': seed.RACK_TYPE_ID, 'type_label': 'Rack',
                              'type_icon': 'fa-server', 'type_selectable': True})
        database_manager.get_collection(CmdbRackMount.COLLECTION, database_name).insert_one({
            'public_id': HIDDEN_MOUNT_ID, 'rack_id': seed.RACK_ID, 'object_id': seed.HIDDEN_ID, 'kind': 'MOUNT',
            'area': 'UNASSIGNED', 'position': 0,
        })
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': seed.RACK_ID},
            {'$push': {'fields': {'type': 'location', 'name': RackField.LOCATION.value, 'value': RACK_NODE_ID}}})

        moved: int = reconcile_member_locations(
            seed.RACK_ID, seed.editor(), objects_manager, LocationsManager(database_manager),
            RackMountsManager(database_manager),
        )

        member_node = locations.find_one({'object_id': seed.HIDDEN_ID})
        assert moved == 1
        assert member_node is not None and member_node['parent'] == RACK_NODE_ID

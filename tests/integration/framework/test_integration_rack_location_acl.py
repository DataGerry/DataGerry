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
Integration tests for the Rack rule of a location write against a real MongoDB and the real ACL

``resolve_rack_location_target`` finds the Rack behind its own node and nothing behind an ordinary one;
``abort_if_rack_unchangeable`` refuses a Rack the seed's editor may only read (the update message) or may not read
(the read message), passes one it may change, and keeps each decision on the target
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    abort_if_rack_unchangeable,
    resolve_rack_location_target,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError
from tests.utils import rack_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

# Every test here reaches the database through ManagerProvider, which reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

ROOT_NODE_ID: int = 1
RACK_NODE_ID: int = 98791
MEMBER_NODE_ID: int = 98792


@pytest.fixture(name='nodes', autouse=True)
def fixture_nodes(database_manager: MongoDatabaseManager, database_name: str):
    """The rack ACL seed, a node for RACK and one for an ordinary object"""
    seed.seed(database_manager, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    locations.delete_many({'public_id': {'$in': [RACK_NODE_ID, MEMBER_NODE_ID]}})
    locations.insert_many([
        {'public_id': RACK_NODE_ID, 'name': 'rack', 'parent': ROOT_NODE_ID, 'object_id': seed.RACK_ID,
         'type_id': seed.RACK_TYPE_ID, 'type_selectable': True},
        {'public_id': MEMBER_NODE_ID, 'name': 'member', 'parent': ROOT_NODE_ID, 'object_id': seed.OPEN_ID,
         'type_id': seed.OPEN_TYPE_ID, 'type_selectable': True},
    ])

    yield

    locations.delete_many({'public_id': {'$in': [RACK_NODE_ID, MEMBER_NODE_ID]}})
    seed.purge(database_manager, database_name)


def _stored(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> dict[str, Any]:
    """A seeded object as stored"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
        {'public_id': object_id}, {'_id': 0},
    )


@pytest.mark.parametrize('parent, rack_id', [
    (RACK_NODE_ID, seed.RACK_ID), (MEMBER_NODE_ID, None), (None, None),
], ids=['rack-node', 'ordinary-node', 'cleared'])
def test_the_target_is_the_rack_behind_its_own_node(database_manager: MongoDatabaseManager, parent: int | None,
                                                    rack_id: int | None) -> None:
    """Read through the real managers"""
    target = resolve_rack_location_target(seed.editor(), parent, LocationsManager(database_manager))

    assert target.requested_parent == parent
    assert target.rack_id == rack_id


@pytest.mark.parametrize('rack_id, message', [
    (seed.READ_ONLY_RACK_ID, RackAccessError.RACK_UPDATE_DENIED),
    (seed.HIDDEN_RACK_ID, RackAccessError.RACK_READ_DENIED),
], ids=['read-only', 'hidden'])
def test_a_rack_the_editor_may_not_change_is_refused(database_manager: MongoDatabaseManager, database_name: str,
                                                     rack_id: int, message: RackAccessError) -> None:
    """The real ACL builder decides, and the decision is kept"""
    target = resolve_rack_location_target(seed.editor(), None, LocationsManager(database_manager))
    target.rack = _stored(database_manager, database_name, rack_id)

    with pytest.raises(HTTPException) as caught:
        abort_if_rack_unchangeable(target, rack_id, ObjectsManager(database_manager), seed.editor())

    assert caught.value.code == HTTPStatus.FORBIDDEN
    assert caught.value.description == message.format(object_id=rack_id)
    assert target.write_blockers[rack_id] == message.format(object_id=rack_id)


def test_a_rack_the_editor_may_change_passes(database_manager: MongoDatabaseManager) -> None:
    """Read from the database when the target is another Rack"""
    target = resolve_rack_location_target(seed.editor(), RACK_NODE_ID, LocationsManager(database_manager))

    abort_if_rack_unchangeable(target, seed.OTHER_RACK_ID, ObjectsManager(database_manager), seed.editor())

    assert target.write_blockers == {seed.OTHER_RACK_ID: None}

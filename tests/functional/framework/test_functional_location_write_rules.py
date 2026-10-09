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
What `PATCH /locations/<object_id>/parent` demands of the object it places

A node carries its object's summary as its name, so the move reads the object through the caller's READ ACL first
and a denial is a 403 before anything is written. Requested as the admin group (which may read the hidden type) and
as a group holding the location rights alone. The move writes the node under the placement rules: the object must
exist and declare a location field, the parent must exist and be selectable, the node takes the object's own type,
and the object's location field is pointed at the parent
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_NOT_FOUND_MSG,
)
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the location-write fixture for each test and removes it after."""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    yield
    seed.purge(database_manager, database_name)


def _move(rest_api, object_id: int, parent: int = seed.PARENT_NODE_ID, as_editor: bool = False):
    """PATCHes `object_id` under `parent`, as the admin or as the location editor."""
    user: dict[str, Any] = {'user': seed.location_editor()} if as_editor else {}

    return rest_api.patch(f'/locations/{object_id}/parent', json={LocationKey.PARENT.value: parent}, **user)


def _seed_node(database_manager: MongoDatabaseManager, database_name: str, node_id: int, object_id: int,
               type_id: int) -> None:
    """Places `object_id` at the root with a stored name, so the move has a node to re-parent."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one(
        seed.node_doc(node_id, object_id, RootLocationDefault.PUBLIC_ID, type_id=type_id))


class TestPlacingReadsTheObject:
    """The object read, on an object not yet placed."""

    def test_the_admin_gets_the_derived_name(self, rest_api, database_manager, database_name) -> None:
        """The control: a reader of the hidden type places it, the node named after the object's summary"""
        assert _move(rest_api, seed.HIDDEN_ID).status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, seed.HIDDEN_ID)['name'] == seed.HIDDEN_VALUE

    def test_a_hidden_object_is_a_403(self, rest_api, database_manager, database_name) -> None:
        """The editor may not read the object, so it may not name a node after it - and nothing is written"""
        response = _move(rest_api, seed.HIDDEN_ID, as_editor=True)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == LINKED_OBJECT_DENIED_MSG.format(object_id=seed.HIDDEN_ID)
        assert seed.stored_node(database_manager, database_name, seed.HIDDEN_ID) is None
        assert seed.location_value(database_manager, database_name, seed.HIDDEN_ID) is None

    def test_a_readable_object_is_placed(self, rest_api, database_manager, database_name) -> None:
        """The control for the editor: the denial is by type"""
        assert _move(rest_api, seed.VISIBLE_ID, as_editor=True).status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)['name'] == seed.VISIBLE_VALUE

    def test_a_missing_object_is_a_404(self, rest_api, database_manager, database_name) -> None:
        """No node for an object that does not exist"""
        response = _move(rest_api, seed.MISSING_OBJECT_ID)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == LINKED_OBJECT_NOT_FOUND_MSG.format(object_id=seed.MISSING_OBJECT_ID)
        assert seed.stored_node(database_manager, database_name, seed.MISSING_OBJECT_ID) is None


class TestPlacingFollowsThePlacementRules:
    """The placement rules and the mirror."""

    def test_an_object_without_a_location_field_is_a_400(self, rest_api, database_manager, database_name) -> None:
        """Only an object with a location field can sit in the tree"""
        assert _move(rest_api, seed.PLAIN_ID).status_code == HTTPStatus.BAD_REQUEST
        assert seed.stored_node(database_manager, database_name, seed.PLAIN_ID) is None

    def test_a_parent_that_does_not_exist_is_a_400(self, rest_api, database_manager, database_name) -> None:
        """The parent must exist"""
        assert _move(rest_api, seed.VISIBLE_ID, parent=seed.MISSING_OBJECT_ID).status_code == HTTPStatus.BAD_REQUEST
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None

    def test_an_unselectable_parent_is_a_400(self, rest_api, database_manager, database_name) -> None:
        """The parent must be selectable as a parent"""
        response = _move(rest_api, seed.VISIBLE_ID, parent=seed.UNSELECTABLE_NODE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None

    def test_the_object_location_field_follows_the_node(self, rest_api, database_manager, database_name) -> None:
        """Both halves of the mirror: the node's parent and the object's location field agree"""
        assert _move(rest_api, seed.VISIBLE_ID).status_code == HTTPStatus.OK

        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)['parent'] == seed.PARENT_NODE_ID
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == seed.PARENT_NODE_ID

    def test_the_node_takes_the_objects_own_type(self, rest_api, database_manager, database_name) -> None:
        """The type fields are the object's type's"""
        assert _move(rest_api, seed.VISIBLE_ID).status_code == HTTPStatus.OK

        node: dict[str, Any] = seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)
        assert node['type_id'] == seed.VISIBLE_TYPE_ID
        assert node['type_label'] == seed.type_label(seed.VISIBLE_TYPE_ID)


class TestReParentingReadsTheObject:
    """The object read, on an object already placed: the moved node is renamed after the summary."""

    def test_the_admin_gets_the_derived_name(self, rest_api, database_manager, database_name) -> None:
        """The control: the stored name is replaced by the hidden object's summary for a reader of its type"""
        _seed_node(database_manager, database_name, seed.HIDDEN_NODE_ID, seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID)

        assert _move(rest_api, seed.HIDDEN_ID).status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, seed.HIDDEN_ID)['name'] == seed.HIDDEN_VALUE

    def test_a_hidden_object_is_a_403(self, rest_api, database_manager, database_name) -> None:
        """The editor gets neither the summary nor a write"""
        _seed_node(database_manager, database_name, seed.HIDDEN_NODE_ID, seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID)

        response = _move(rest_api, seed.HIDDEN_ID, as_editor=True)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert seed.HIDDEN_VALUE not in response.get_data(as_text=True)
        node: dict[str, Any] = seed.stored_node(database_manager, database_name, seed.HIDDEN_ID)
        assert (node['name'], node['parent']) == (seed.STORED_NODE_NAME, RootLocationDefault.PUBLIC_ID)
        assert seed.location_value(database_manager, database_name, seed.HIDDEN_ID) is None

    def test_a_readable_object_is_re_parented(self, rest_api, database_manager, database_name) -> None:
        """The control for the editor"""
        _seed_node(database_manager, database_name, seed.VISIBLE_NODE_ID, seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID)

        assert _move(rest_api, seed.VISIBLE_ID, as_editor=True).status_code == HTTPStatus.OK
        node: dict[str, Any] = seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)
        assert (node['name'], node['parent']) == (seed.VISIBLE_VALUE, seed.PARENT_NODE_ID)

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
What every CmdbLocation write demands of the object it places

A placement write is a READ of its object (the node is named after the object's summary) and an UPDATE of it (the
object's location field is written). So both moves - the only placement writes, placing, re-parenting and removing
alike - ask the caller's ACL for both on the object's type, and an active type, before any other check - a
denial is a 403 and nothing is written. Requested as a group holding the location rights alone: it reads and
changes VISIBLE, reads but may not change READ_ONLY, and may not read HIDDEN. DEACTIVATED is refused to the admin
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_UPDATE_DENIED_MSG,
)
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.object_model import CmdbObject
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

BULK_MOVE_URL: str = '/locations/parents'
BULK_MOVE_IDS_KEY: str = 'object_ids'
DEACTIVATED_MARKER: str = 'deactivated'
ROUTES_MODULE: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'

# Nodes this module writes itself, under PARENT_NODE_ID: one for each object a move starts from
OWN_NODE_IDS: dict[int, int] = {
    seed.VISIBLE_ID: 89561, seed.HIDDEN_ID: 89562, seed.READ_ONLY_ID: 89563, seed.DEACTIVATED_ID: 89564,
}
CHILD_NODE_ID: int = 89566


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the location-write fixture for each test and removes it after."""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    yield
    seed.purge(database_manager, database_name)
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': [*OWN_NODE_IDS.values(), CHILD_NODE_ID]}})


def _place(database_manager: MongoDatabaseManager, database_name: str, object_id: int,
           node_id: int | None = None, parent: int = seed.PARENT_NODE_ID) -> None:
    """Writes a node for `object_id` under `parent` and points its location field there - straight into the DB."""
    type_id: int = seed.load(database_manager, database_name, object_id).type_id
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one(
        seed.node_doc(node_id or OWN_NODE_IDS[object_id], object_id, parent, type_id=type_id))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
        {'public_id': object_id, 'fields.name': seed.LOCATION_FIELD}, {'$set': {'fields.$.value': parent}})


def _editor() -> dict[str, Any]:
    """The request kwargs that send it as the location editor."""
    return {'user': seed.location_editor()}


def _denied_message(object_id: int) -> str:
    """The 403 of an object the caller may not read."""
    return LINKED_OBJECT_DENIED_MSG.format(object_id=object_id)


def _update_denied_message(object_id: int) -> str:
    """The 403 of an object the caller may read but not change."""
    return LINKED_OBJECT_UPDATE_DENIED_MSG.format(object_id=object_id)


# (object, send as the editor, the 403's message - None means the deactivated type's)
REFUSALS: list[Any] = [
    pytest.param(seed.HIDDEN_ID, True, _denied_message(seed.HIDDEN_ID), id='not-readable'),
    pytest.param(seed.READ_ONLY_ID, True, _update_denied_message(seed.READ_ONLY_ID), id='read-only'),
    pytest.param(seed.DEACTIVATED_ID, False, None, id='deactivated-type'),
]


def _assert_refused(response: Any, message: str | None) -> None:
    """A 403 with the expected message."""
    assert response.status_code == HTTPStatus.FORBIDDEN

    if message is None:
        assert DEACTIVATED_MARKER in response.get_json()['message']
    else:
        assert response.get_json()['message'] == message


class TestTheSingleMove:
    """PATCH /locations/<object_id>/parent - the tree organizer's drag-and-drop."""

    @pytest.mark.parametrize('object_id, as_editor, message', REFUSALS)
    def test_a_refused_object_is_not_moved(self, rest_api, database_manager, database_name, object_id: int,
                                           as_editor: bool, message: str | None) -> None:
        """403, and the node and the field stay where they were"""
        _place(database_manager, database_name, object_id)

        response = rest_api.patch(f'/locations/{object_id}/parent', json={LocationKey.PARENT.value: None},
                                  **(_editor() if as_editor else {}))

        _assert_refused(response, message)
        assert seed.stored_node(database_manager, database_name, object_id)['parent'] == seed.PARENT_NODE_ID
        assert seed.location_value(database_manager, database_name, object_id) == seed.PARENT_NODE_ID

    def test_an_object_the_editor_may_change_is_moved(self, rest_api, database_manager, database_name) -> None:
        """READ and UPDATE granted: the drop is applied"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.OK
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == seed.PARENT_NODE_ID

    def test_a_placed_object_the_editor_may_change_is_re_parented(
            self, rest_api, database_manager, database_name) -> None:
        """READ and UPDATE granted: node and field both follow the drop"""
        _place(database_manager, database_name, seed.VISIBLE_ID)

        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                                  json={LocationKey.PARENT.value: RootLocationDefault.PUBLIC_ID}, **_editor())

        assert response.status_code == HTTPStatus.OK
        node: dict[str, Any] = seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)
        assert node['parent'] == RootLocationDefault.PUBLIC_ID
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == RootLocationDefault.PUBLIC_ID

    def test_a_changeable_objects_placement_is_removed(self, rest_api, database_manager, database_name) -> None:
        """A null parent: the node goes and the field is cleared"""
        _place(database_manager, database_name, seed.VISIBLE_ID)

        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent', json={LocationKey.PARENT.value: None},
                                  **_editor())

        assert response.status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) is None

    def test_a_re_pointed_child_needs_no_acl_of_its_own(self, rest_api, database_manager, database_name) -> None:
        """A read-only child follows its removed parent onto the grandparent - a consequence of the removal"""
        _place(database_manager, database_name, seed.VISIBLE_ID)
        _place(database_manager, database_name, seed.READ_ONLY_ID, node_id=CHILD_NODE_ID,
               parent=OWN_NODE_IDS[seed.VISIBLE_ID])

        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent', json={LocationKey.PARENT.value: None},
                                  **_editor())

        assert response.status_code == HTTPStatus.OK
        assert seed.location_value(database_manager, database_name, seed.READ_ONLY_ID) == seed.PARENT_NODE_ID

    def test_the_acl_answers_before_the_drop_target_is_judged(self, rest_api) -> None:
        """A hidden object dropped onto an unselectable node: the 403, not the target's 400"""
        response = rest_api.patch(f'/locations/{seed.HIDDEN_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.UNSELECTABLE_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _denied_message(seed.HIDDEN_ID)


class TestTheBatchMove:
    """PATCH /locations/parents - the multi-select drag-and-drop."""

    def test_one_refused_object_refuses_the_whole_batch(self, rest_api, database_manager, database_name) -> None:
        """The changeable object listed first is not moved either"""
        response = rest_api.patch(BULK_MOVE_URL, json={BULK_MOVE_IDS_KEY: [seed.VISIBLE_ID, seed.READ_ONLY_ID],
                                                       LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _update_denied_message(seed.READ_ONLY_ID)
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) is None
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None

    @pytest.mark.parametrize('object_id, as_editor, message', REFUSALS)
    def test_each_refusal_is_the_singles(self, rest_api, object_id: int, as_editor: bool,
                                         message: str | None) -> None:
        """The batch answers what the single move would"""
        response = rest_api.patch(BULK_MOVE_URL, json={BULK_MOVE_IDS_KEY: [object_id],
                                                       LocationKey.PARENT.value: seed.PARENT_NODE_ID},
                                  **(_editor() if as_editor else {}))

        _assert_refused(response, message)

    def test_the_acl_answers_before_the_shared_parent_is_judged(self, rest_api) -> None:
        """A hidden object and an unselectable parent: the 403, not the parent's 400"""
        response = rest_api.patch(BULK_MOVE_URL, json={BULK_MOVE_IDS_KEY: [seed.HIDDEN_ID],
                                                       LocationKey.PARENT.value: seed.UNSELECTABLE_NODE_ID},
                                  **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_changeable_objects_are_moved(self, rest_api, database_manager, database_name) -> None:
        """Every object granted: the batch is applied"""
        response = rest_api.patch(BULK_MOVE_URL, json={BULK_MOVE_IDS_KEY: [seed.VISIBLE_ID, seed.SUMMARY_REF_ID],
                                                       LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.OK
        assert seed.location_value(database_manager, database_name, seed.SUMMARY_REF_ID) == seed.PARENT_NODE_ID


class TestTheAclComesBeforeTheRackRules:
    """A caller who may not touch the object learns nothing of the Rack rules either."""

    RACK_REFUSAL: str = 'the rack guard refused it'

    @pytest.fixture(autouse=True)
    def _refusing_rack_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every rack check refuses - a request that reaches it answers its 400"""
        def _refuse(*_args: Any, **_kwargs: Any) -> None:
            abort(HTTPStatus.BAD_REQUEST, self.RACK_REFUSAL)

        monkeypatch.setattr(f'{ROUTES_MODULE}.guard_rack_location_change', _refuse)

    def test_the_single_move(self, rest_api) -> None:
        """PATCH /locations/<object_id>/parent"""
        response = rest_api.patch(f'/locations/{seed.READ_ONLY_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_the_batch_move(self, rest_api) -> None:
        """PATCH /locations/parents"""
        response = rest_api.patch(BULK_MOVE_URL, json={BULK_MOVE_IDS_KEY: [seed.READ_ONLY_ID],
                                                       LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_a_granted_request_does_reach_the_rack_rules(self, rest_api) -> None:
        """The fixture is live: an object the editor may change gets the rack guard's 400"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_editor())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == self.RACK_REFUSAL

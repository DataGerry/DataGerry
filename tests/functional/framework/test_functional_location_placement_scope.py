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
Where a placement may name its parent: only a node the caller can see

The tree read hides a node whose branch passes through a Type the caller may not READ, so every placement write
refuses such a parent with the location 403 before anything is written - the single and the bulk move, and the
object create and update that carry a location field. Requested as a group holding the location rights and the
object add / edit rights, but not READ on the hidden Type; the admin group is the control
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    BULK_MOVE_OBJECT_IDS_KEY,
    LOCATION_NOT_READABLE_MSG,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model.field_type_enum import FieldType
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

BULK_MOVE_URL: str = '/locations/parents'
OBJECTS_URL: str = '/objects'

# A node of a readable Type that sits under the hidden node, and the object it stands for (never stored)
UNDER_HIDDEN_NODE_ID: int = seed.VISIBLE_NODE_ID
UNDER_HIDDEN_NODE_OBJECT_ID: int = 89533

# The object the create tests write
CREATED_ID: int = 89571
CREATED_VALUE: str = 'created-under-a-parent'


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the fixture, a hidden node with a readable child, and object rights for the editor; removes all of it
    after, with the object logs the writes left behind"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_many([
        seed.node_doc(seed.HIDDEN_NODE_ID, seed.HIDDEN_ID, RootLocationDefault.PUBLIC_ID, type_id=seed.HIDDEN_TYPE_ID),
        seed.node_doc(UNDER_HIDDEN_NODE_ID, UNDER_HIDDEN_NODE_OBJECT_ID, seed.HIDDEN_NODE_ID),
    ])
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID},
        {'$push': {'rights': {'$each': [ObjectRightName.ADD.value, ObjectRightName.EDIT.value]}}},
    )
    yield
    seed.purge(database_manager, database_name)
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'public_id': CREATED_ID})
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many({'object_id': CREATED_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': [seed.VISIBLE_ID, CREATED_ID]}})


def _as(as_editor: bool) -> dict[str, Any]:
    """The request kwargs naming the location editor, or none for the admin."""
    return {'user': seed.location_editor()} if as_editor else {}


def _refusal(parent: int) -> str:
    """The 403 message a hidden `parent` is refused with."""
    return LOCATION_NOT_READABLE_MSG.format(public_id=parent)


def _object_payload(public_id: int, value: str, parent: int) -> dict[str, Any]:
    """A full VISIBLE-type object body whose location field names `parent`."""
    return {
        'public_id': public_id, 'type_id': seed.VISIBLE_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'fields': [
            {'type': FieldType.TEXT.value, 'name': seed.NAME_FIELD, 'value': value},
            {'type': FieldType.LOCATION.value, 'name': seed.LOCATION_FIELD, 'value': parent},
        ],
    }


HIDDEN_PARENTS: list[int] = [seed.HIDDEN_NODE_ID, UNDER_HIDDEN_NODE_ID]


class TestTheSingleMove:
    """PATCH /locations/<object_id>/parent."""

    @pytest.mark.parametrize('parent', HIDDEN_PARENTS)
    def test_a_hidden_parent_is_a_403(self, rest_api, database_manager, database_name, parent: int) -> None:
        """The hidden node itself and a readable node below it - nothing is written"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent', json={LocationKey.PARENT.value: parent},
                                  **_as(True))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _refusal(parent)
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) is None

    @pytest.mark.parametrize('parent', HIDDEN_PARENTS)
    def test_the_admin_may_place_there(self, rest_api, database_manager, database_name, parent: int) -> None:
        """The control: a reader of the hidden Type places the object"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent', json={LocationKey.PARENT.value: parent})

        assert response.status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)['parent'] == parent

    def test_a_visible_parent_is_placed(self, rest_api, database_manager, database_name) -> None:
        """The control for the editor: the refusal is by branch"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.PARENT_NODE_ID}, **_as(True))

        assert response.status_code == HTTPStatus.OK
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == seed.PARENT_NODE_ID

    def test_a_missing_parent_stays_a_400(self, rest_api) -> None:
        """Existence is judged before readability"""
        response = rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                                  json={LocationKey.PARENT.value: seed.MISSING_OBJECT_ID}, **_as(True))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestTheBulkMove:
    """PATCH /locations/parents - one hidden parent refuses the whole batch."""

    @pytest.mark.parametrize('parent', HIDDEN_PARENTS)
    def test_a_hidden_parent_is_a_403(self, rest_api, database_manager, database_name, parent: int) -> None:
        """Neither listed object is moved"""
        response = rest_api.patch(BULK_MOVE_URL, json={
            BULK_MOVE_OBJECT_IDS_KEY: [seed.VISIBLE_ID, seed.SUMMARY_REF_ID], LocationKey.PARENT.value: parent,
        }, **_as(True))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _refusal(parent)

        for object_id in (seed.VISIBLE_ID, seed.SUMMARY_REF_ID):
            assert seed.stored_node(database_manager, database_name, object_id) is None
            assert seed.location_value(database_manager, database_name, object_id) is None

    def test_the_admin_may_move_there(self, rest_api, database_manager, database_name) -> None:
        """The control"""
        response = rest_api.patch(BULK_MOVE_URL, json={
            BULK_MOVE_OBJECT_IDS_KEY: [seed.VISIBLE_ID], LocationKey.PARENT.value: UNDER_HIDDEN_NODE_ID,
        })

        assert response.status_code == HTTPStatus.OK
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == UNDER_HIDDEN_NODE_ID


class TestTheObjectWrites:
    """POST /objects/ and PUT /objects/<id> with a location field."""

    @pytest.mark.parametrize('parent', HIDDEN_PARENTS)
    def test_a_create_under_a_hidden_parent_is_a_403(self, rest_api, database_manager, database_name,
                                                     parent: int) -> None:
        """No object and no node are written"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(CREATED_ID, CREATED_VALUE, parent),
                                 **_as(True))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _refusal(parent)
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
            {'public_id': CREATED_ID}) is None
        assert seed.stored_node(database_manager, database_name, CREATED_ID) is None

    def test_the_admin_may_create_there(self, rest_api, database_manager, database_name) -> None:
        """The control"""
        response = rest_api.post(f'{OBJECTS_URL}/',
                                 json=_object_payload(CREATED_ID, CREATED_VALUE, UNDER_HIDDEN_NODE_ID))

        assert response.status_code == HTTPStatus.OK
        assert seed.stored_node(database_manager, database_name, CREATED_ID)['parent'] == UNDER_HIDDEN_NODE_ID

    @pytest.mark.parametrize('parent', HIDDEN_PARENTS)
    def test_an_update_under_a_hidden_parent_is_a_403(self, rest_api, database_manager, database_name,
                                                      parent: int) -> None:
        """The object keeps its stored location field, and no node is written"""
        response = rest_api.put(f'{OBJECTS_URL}/{seed.VISIBLE_ID}',
                                json=_object_payload(seed.VISIBLE_ID, seed.VISIBLE_VALUE, parent), **_as(True))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _refusal(parent)
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID) is None
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) is None

    def test_an_unchanged_hidden_parent_is_not_judged(self, rest_api, database_manager, database_name) -> None:
        """An object an admin placed under the hidden branch stays editable by the editor"""
        assert rest_api.patch(f'/locations/{seed.VISIBLE_ID}/parent',
                              json={LocationKey.PARENT.value: UNDER_HIDDEN_NODE_ID}).status_code == HTTPStatus.OK

        response = rest_api.put(f'{OBJECTS_URL}/{seed.VISIBLE_ID}',
                                json=_object_payload(seed.VISIBLE_ID, CREATED_VALUE, UNDER_HIDDEN_NODE_ID),
                                **_as(True))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert seed.location_value(database_manager, database_name, seed.VISIBLE_ID) == UNDER_HIDDEN_NODE_ID

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
Functional smoke for the CmdbLocation an object write maintains

An object carrying a location field owns a node in the location tree, and the object routes are what
keep the two in step: a create places the node, an edit re-parents it, clearing the field removes it,
and a delete takes the subtree's children with it. The rules live in ``workflows/locations.md``;
these tests drive them through the object routes, which is where a client actually triggers them
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.location_model.cmdb_location import CmdbLocation

from tests.functional.framework.objects.objects_route_helpers import (
    LOCATIONS_ROUTE_URL,
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROOT_LOCATION_ID,
    ROUTE_URL,
    SEED_AUTHOR_ID,
    SEED_VERSION,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOCATION_FIELD_NAME: str = 'dg_location'

LSYNC_TYPE_ID: int = 9404

LSYNC_OBJECT_ID: int = 9470

LSYNC_CHILD_OBJECT_ID: int = 9471

LSYNC_PARENT_A: int = 9490

LSYNC_PARENT_B: int = 9491

LSYNC_OWN_LOCATION: int = 9492

LSYNC_CHILD_LOCATION: int = 9493

LSYNC_NONSELECTABLE_LOC: int = 9494

NONEXISTENT_PARENT: int = 88888

CUSTOM_LOCATION_NAME: str = 'Custom Location Name'


def _location_type_doc() -> dict[str, Any]:
    """A CmdbType carrying a location-typed field, so its objects mirror into the CmdbLocation tree."""
    return {
        'public_id': LSYNC_TYPE_ID,
        'name': f'loc-type-{LSYNC_TYPE_ID}',
        'label': 'Location Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'location', 'name': LOCATION_FIELD_NAME, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [NAME_FIELD, LOCATION_FIELD_NAME]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _loc_object_payload(public_id: int, parent: int | None) -> dict[str, Any]:
    """POST/PUT body for a LOC_TYPE object placed under `parent` (0/None => no location)."""
    return {
        'public_id': public_id,
        'type_id': LSYNC_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'value': ORIGINAL_VALUE},
            {'type': 'location', 'name': LOCATION_FIELD_NAME, 'value': parent},
        ],
    }


def _loc_doc(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation doc for direct insertion into the locations collection."""
    return {
        'public_id': public_id,
        'name': f'loc-{public_id}',
        'parent': parent,
        'object_id': object_id,
        'type_id': LSYNC_TYPE_ID,
        'type_label': 'Location Type',
        'type_icon': 'fa-cube',
        'type_selectable': True,
    }


class TestObjectLocationSync:
    """POST/PUT/PATCH mirror the object's location field into the CmdbLocation tree and validate it."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the location-field type and two selectable parent locations; cleans everything after."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)

        types.insert_one(_location_type_doc())
        locations.insert_many([
            _loc_doc(LSYNC_PARENT_A, 9480, ROOT_LOCATION_ID),
            _loc_doc(LSYNC_PARENT_B, 9481, ROOT_LOCATION_ID),
        ])
        yield
        types.delete_one({'public_id': LSYNC_TYPE_ID})
        objects.delete_many({'public_id': {'$in': [LSYNC_OBJECT_ID, LSYNC_CHILD_OBJECT_ID]}})
        locations.delete_many(
            {'public_id': {'$in': [LSYNC_PARENT_A, LSYNC_PARENT_B, LSYNC_OWN_LOCATION, LSYNC_CHILD_LOCATION]}}
        )
        locations.delete_many({'object_id': {'$in': [LSYNC_OBJECT_ID, LSYNC_CHILD_OBJECT_ID]}})

    @staticmethod
    def _location_of(database_manager: MongoDatabaseManager, database_name: str, object_id: int):
        """Returns the CmdbLocation doc linked to the given object, or None."""
        return database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
            .find_one({'object_id': object_id})

    # ---- CREATE ---- #
    def test_post_creates_location_for_new_object(self, rest_api, database_manager, database_name) -> None:
        """POSTing an object with a parent creates a mirrored CmdbLocation carrying that parent."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        assert response.status_code == HTTPStatus.OK
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location is not None
        assert location['parent'] == LSYNC_PARENT_A

    def test_post_uses_custom_location_name(self, rest_api, database_manager, database_name) -> None:
        """A location_name in the POST body is used verbatim as the CmdbLocation tree name."""
        payload = _loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A)
        payload['location_name'] = CUSTOM_LOCATION_NAME

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.OK
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location['name'] == CUSTOM_LOCATION_NAME

    def test_post_without_parent_creates_no_location(self, rest_api, database_manager, database_name) -> None:
        """POSTing an object with no parent leaves the location tree untouched."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.OK
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None

    def test_post_nonexistent_parent_rejected(self, rest_api) -> None:
        """POSTing under a parent location that does not exist is rejected 400 (object not created)."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, NONEXISTENT_PARENT))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/native/{LSYNC_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_post_under_non_selectable_parent_rejected(self, rest_api, database_manager, database_name) -> None:
        """POSTing under a parent whose type is not selectable-as-parent is rejected 400 (object not created)."""
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        non_selectable = _loc_doc(LSYNC_NONSELECTABLE_LOC, 9479, ROOT_LOCATION_ID)
        non_selectable['type_selectable'] = False
        locations.insert_one(non_selectable)
        try:
            response = rest_api.post(f'{ROUTE_URL}/',
                                     json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_NONSELECTABLE_LOC))

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert rest_api.get(f'{ROUTE_URL}/native/{LSYNC_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND
        finally:
            locations.delete_many({'public_id': LSYNC_NONSELECTABLE_LOC})

    # ---- EDIT (PUT) ---- #
    def test_put_updates_location_parent(self, rest_api, database_manager, database_name) -> None:
        """Changing the object's location field via PUT moves its CmdbLocation to the new parent."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_B))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)['parent'] == LSYNC_PARENT_B

    def test_put_removes_location_when_parent_cleared(self, rest_api, database_manager, database_name) -> None:
        """Clearing the location field via PUT deletes the object's (childless) CmdbLocation."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None

    def test_put_nonexistent_parent_rejected(self, rest_api, database_manager, database_name) -> None:
        """Moving to a parent location that does not exist is rejected 400."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, NONEXISTENT_PARENT))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_put_cycle_rejected(self, rest_api, database_manager, database_name) -> None:
        """Setting the parent to a location inside the object's own subtree is rejected 400 (cycle)."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, ROOT_LOCATION_ID),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, ROOT_LOCATION_ID))
        locations.insert_one(_loc_doc(LSYNC_CHILD_LOCATION, LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_CHILD_LOCATION))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_put_remove_with_children_promotes_them(self, rest_api, database_manager, database_name) -> None:
        """Clearing the location promotes children to the grandparent - both the child location NODE
        and the child OBJECT's mirrored location field (the two-collection mirror, end to end)."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, ROOT_LOCATION_ID),
                            'creation_time': datetime.now(timezone.utc)})
        # the child object is placed under the parent's location (its dg_location field points there)
        objects.insert_one({**_loc_object_payload(LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, ROOT_LOCATION_ID))
        locations.insert_one(_loc_doc(LSYNC_CHILD_LOCATION, LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.ACCEPTED
        # the object's own placement is removed
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None
        # the child location NODE survives, promoted onto the removed node's own parent (the root)
        child_node = locations.find_one({'public_id': LSYNC_CHILD_LOCATION})
        assert child_node is not None and child_node['parent'] == ROOT_LOCATION_ID
        # and the child OBJECT's mirrored location field is re-pointed at the grandparent too
        child_object = objects.find_one({'public_id': LSYNC_CHILD_OBJECT_ID})
        location_field = next(f for f in child_object['fields'] if f['name'] == LOCATION_FIELD_NAME)
        assert location_field['value'] == ROOT_LOCATION_ID

    # ---- PATCH (name-only) ---- #
    def test_patch_location_name_only_renames_node(self, rest_api, database_manager, database_name) -> None:
        """A name-only PATCH renames the CmdbLocation without a field change and is not rejected as empty."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.patch(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}', json={'location_name': CUSTOM_LOCATION_NAME})

        assert response.status_code == HTTPStatus.ACCEPTED
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location['name'] == CUSTOM_LOCATION_NAME
        assert location['parent'] == LSYNC_PARENT_A

    # ---- MOVE (drag & drop) ---- #
    def test_move_single_reparents_node_and_object_field(self, rest_api, database_manager, database_name) -> None:
        """PATCH /locations/<id>/parent moves the node to the new parent and mirrors the object field."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.patch(f'{LOCATIONS_ROUTE_URL}/{LSYNC_OBJECT_ID}/parent', json={'parent': LSYNC_PARENT_B})

        assert response.status_code == HTTPStatus.OK
        # the location NODE now points at the new parent
        assert locations.find_one({'object_id': LSYNC_OBJECT_ID})['parent'] == LSYNC_PARENT_B
        # and the object's mirrored location field is updated too
        moved_object = objects.find_one({'public_id': LSYNC_OBJECT_ID})
        location_field = next(f for f in moved_object['fields'] if f['name'] == LOCATION_FIELD_NAME)
        assert location_field['value'] == LSYNC_PARENT_B

    def test_move_single_under_non_selectable_parent_rejected(
        self, rest_api, database_manager, database_name,
    ) -> None:
        """A move onto a parent whose type is not selectable-as-parent is rejected 400 (unchanged)."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        non_selectable = _loc_doc(LSYNC_NONSELECTABLE_LOC, 9479, ROOT_LOCATION_ID)
        non_selectable['type_selectable'] = False
        locations.insert_one(non_selectable)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))
        try:
            response = rest_api.patch(f'{LOCATIONS_ROUTE_URL}/{LSYNC_OBJECT_ID}/parent',
                                      json={'parent': LSYNC_NONSELECTABLE_LOC})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # the placement is unchanged
            assert locations.find_one({'object_id': LSYNC_OBJECT_ID})['parent'] == LSYNC_PARENT_A
        finally:
            locations.delete_many({'public_id': LSYNC_NONSELECTABLE_LOC})

    def test_move_many_reparents_all_targets(self, rest_api, database_manager, database_name) -> None:
        """PATCH /locations/parents moves every listed object's placement under the common parent."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        objects.insert_one({**_loc_object_payload(LSYNC_CHILD_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))
        locations.insert_one(_loc_doc(LSYNC_CHILD_LOCATION, LSYNC_CHILD_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.patch(f'{LOCATIONS_ROUTE_URL}/parents',
                                  json={'object_ids': [LSYNC_OBJECT_ID, LSYNC_CHILD_OBJECT_ID],
                                        'parent': LSYNC_PARENT_B})

        assert response.status_code == HTTPStatus.OK
        assert locations.find_one({'object_id': LSYNC_OBJECT_ID})['parent'] == LSYNC_PARENT_B
        assert locations.find_one({'object_id': LSYNC_CHILD_OBJECT_ID})['parent'] == LSYNC_PARENT_B

    def test_move_many_is_atomic_on_an_invalid_target(self, rest_api, database_manager, database_name) -> None:
        """One invalid target (missing object) rejects the whole batch; the valid target is untouched."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.patch(f'{LOCATIONS_ROUTE_URL}/parents',
                                  json={'object_ids': [LSYNC_OBJECT_ID, NONEXISTENT_PARENT],
                                        'parent': LSYNC_PARENT_B})

        assert response.status_code == HTTPStatus.NOT_FOUND
        # the valid target was NOT moved - the batch is atomic
        assert locations.find_one({'object_id': LSYNC_OBJECT_ID})['parent'] == LSYNC_PARENT_A

    def test_move_many_empty_list_rejected(self, rest_api) -> None:
        """An empty object_ids list is rejected 400."""
        response = rest_api.patch(f'{LOCATIONS_ROUTE_URL}/parents', json={'object_ids': [], 'parent': LSYNC_PARENT_B})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    # ---- UPDATE_LOCATION route mirrors both sides ---- #
    def test_update_location_route_mirrors_object_field(self, rest_api, database_manager, database_name) -> None:
        """PUT /locations/update_location updates the node AND the object's mirrored location field."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(
            f'{LOCATIONS_ROUTE_URL}/update_location',
            json={'object_id': LSYNC_OBJECT_ID, 'parent': LSYNC_PARENT_B, 'name': 'moved'},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        # the location NODE points at the new parent
        assert locations.find_one({'object_id': LSYNC_OBJECT_ID})['parent'] == LSYNC_PARENT_B
        # and the object's mirrored location field matches it (no desync)
        moved_object = objects.find_one({'public_id': LSYNC_OBJECT_ID})
        location_field = next(f for f in moved_object['fields'] if f['name'] == LOCATION_FIELD_NAME)
        assert location_field['value'] == LSYNC_PARENT_B

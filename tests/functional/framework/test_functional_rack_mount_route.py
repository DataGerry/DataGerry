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
Functional tests for the CmdbRackMount REST routes

Walks the whole membership / placement lifecycle over HTTP against a real MongoDB: assign an object to
a rack without placing it, place it, move it, unplace it, remove it. Also covers the refusals that
matter - a rack inside a rack, an object in two racks, overlapping slots, a mount sticking out of the
rack, and a mount addressed through the wrong rack - and that the rack and object ids can not be
rewritten by the payload
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.errors.manager.rack_mounts_manager import (
    RackMountsManagerInsertError,
    RackMountsManagerGetError,
    RackMountsManagerUpdateError,
    RackMountsManagerDeleteError,
)
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/racks'
OBJECTS_URL: str = '/objects'

RACK_TYPE_ID: int = 9551
PLAIN_TYPE_ID: int = 9552

RACK_ID: int = 9561
OTHER_RACK_ID: int = 9562
OBJECT_ID: int = 9571
OTHER_OBJECT_ID: int = 9572

RACK_HEIGHT: int = 42
PLAIN_FIELD: str = 'plain-field'
MEMBER_TYPE_LABEL: str = 'Member'
MEMBER_TYPE_ICON: str = 'fa-cube'
MEMBER_TYPE_COLOR: str = '#4b9e46'

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [RACK_ID, OTHER_RACK_ID, OBJECT_ID, OTHER_OBJECT_ID]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'


def _rack_type_doc() -> dict[str, Any]:
    """The Rack CmdbType"""
    return {
        'public_id': RACK_TYPE_ID,
        'name': 'rack-mount-type',
        'label': 'Rack',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
        ],
        'render_meta': {
            'icon': 'fa-server',
            'sections': [{
                'type': 'section',
                'name': RackSection.INFORMATION.value,
                'label': 'Information',
                'fields': [RackField.NAME.value, RackField.HEIGHT.value],
            }],
            'summary': {'fields': [RackField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _plain_type_doc() -> dict[str, Any]:
    """An ordinary, mountable CmdbType carrying the colour the user picked for it"""
    return {
        'public_id': PLAIN_TYPE_ID,
        'ci_explorer_color': MEMBER_TYPE_COLOR,
        'name': 'rack-mount-member',
        'label': MEMBER_TYPE_LABEL,
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': PLAIN_FIELD, 'label': 'Plain'}],
        'render_meta': {
            'icon': MEMBER_TYPE_ICON,
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [PLAIN_FIELD]}],
            'summary': {'fields': [PLAIN_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _rack_doc(public_id: int, name: str) -> dict[str, Any]:
    """A Rack CmdbObject"""
    return {
        'public_id': public_id,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'value': name},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'value': RACK_HEIGHT},
        ],
    }


def _member_doc(public_id: int) -> dict[str, Any]:
    """An ordinary CmdbObject that can be mounted"""
    return {
        'public_id': public_id,
        'type_id': PLAIN_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': PLAIN_FIELD, 'value': f'member-{public_id}'}],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Rack type and a mountable ordinary type for the module"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    types.insert_many([_rack_type_doc(), _plain_type_doc()])

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


@pytest.fixture(autouse=True)
def _seed_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds two racks and two mountable objects, and clears every mount, around each test"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    mounts = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    objects.insert_many([
        _rack_doc(RACK_ID, 'rack-a'),
        _rack_doc(OTHER_RACK_ID, 'rack-b'),
        _member_doc(OBJECT_ID),
        _member_doc(OTHER_OBJECT_ID),
    ])
    mounts.delete_many({'rack_id': {'$in': [RACK_ID, OTHER_RACK_ID]}})

    yield

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    mounts.delete_many({'rack_id': {'$in': [RACK_ID, OTHER_RACK_ID]}})


def _mount(rest_api, rack_id: int = RACK_ID, **body: Any):
    """POSTs a mount request to a rack"""
    payload: dict[str, Any] = {'object_id': OBJECT_ID}
    payload.update(body)

    return rest_api.post(f'{ROUTE_URL}/{rack_id}/mounts/', json=payload)


def _mount_id(response) -> int:
    """Reads the created mount's public_id out of an insert response"""
    return response.get_json()['result_id']


def _stored_mount(mount_id: int) -> dict[str, Any]:
    """A stored mount document, for standing in on a patched read-back"""
    return {
        'public_id': mount_id,
        'rack_id': RACK_ID,
        'object_id': OBJECT_ID,
        'area': RackArea.UNASSIGNED.value,
        'start_slot': None,
        'height': None,
        'position': 0,
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                            assign without placing                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAssignWithoutPlacing:
    """A POST with no area assigns an object to the rack without placing it in it"""

    def test_a_bare_request_lands_in_the_unassigned_bucket(self, rest_api) -> None:
        """This is the "assign objects to the rack but not placed anywhere" case"""
        response = _mount(rest_api)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        created = response.get_json()['raw']
        assert created['area'] == RackArea.UNASSIGNED.value
        assert created['start_slot'] is None

    def test_an_unassigned_member_gets_an_order_index(self, rest_api) -> None:
        """The bucket has no geometry to sort by, so its members are explicitly ordered"""
        first = _mount(rest_api)
        second = _mount(rest_api, object_id=OTHER_OBJECT_ID)

        assert first.get_json()['raw']['position'] == 0
        assert second.get_json()['raw']['position'] == 1

    def test_the_member_appears_in_the_rack_listing(self, rest_api) -> None:
        """The listing is the membership list of the rack"""
        _mount(rest_api)

        response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/')

        assert response.status_code == HTTPStatus.OK
        assert [m['object_id'] for m in response.get_json()] == [OBJECT_ID]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   placing                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPlacing:
    """A POST naming a main area places the object at a slot"""

    def test_a_valid_placement_is_stored(self, rest_api) -> None:
        """The happy path: front, slot 10, three U"""
        response = _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        created = response.get_json()['raw']
        assert (created['area'], created['start_slot'], created['height']) == (RackArea.FRONT.value, 10, 3)

    def test_a_placed_mount_has_no_order_index(self, rest_api) -> None:
        """A main-area mount is ordered by its slots"""
        response = _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        assert response.get_json()['raw']['position'] is None

    def test_a_main_area_placement_without_geometry_is_refused(self, rest_api) -> None:
        """A placement needs a start slot and a height"""
        assert _mount(rest_api, area=RackArea.FRONT.value).status_code == HTTPStatus.BAD_REQUEST

    def test_a_mount_anchored_above_the_rack_is_refused(self, rest_api) -> None:
        """Slot 43 does not exist in a 42U rack"""
        response = _mount(rest_api, area=RackArea.FRONT.value, start_slot=43, height=1)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'above the Rack height' in response.get_data(as_text=True)

    def test_a_mount_reaching_below_the_rack_floor_is_refused(self, rest_api) -> None:
        """A mount grows downward, so a tall one anchored low leaves the rack at the bottom"""
        response = _mount(rest_api, area=RackArea.FRONT.value, start_slot=2, height=4)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'below the bottom' in response.get_data(as_text=True)

    def test_overlapping_slots_are_refused(self, rest_api) -> None:
        """The first covers 8-10; the second would cover 9-10"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        response = _mount(rest_api, object_id=OTHER_OBJECT_ID,
                          area=RackArea.FRONT.value, start_slot=10, height=2)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'occupied' in response.get_data(as_text=True)

    def test_front_and_back_can_share_a_slot(self, rest_api) -> None:
        """The two views are independent"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        response = _mount(rest_api, object_id=OTHER_OBJECT_ID,
                          area=RackArea.BACK.value, start_slot=10, height=3)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_full_depth_mount_blocks_the_other_view(self, rest_api) -> None:
        """A full-depth mount occupies its range in both views, so the back is taken too"""
        _mount(rest_api, area=RackArea.FULL_DEPTH.value, start_slot=10, height=2)

        response = _mount(rest_api, object_id=OTHER_OBJECT_ID,
                          area=RackArea.BACK.value, start_slot=10, height=1)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_side_mount_needs_no_geometry(self, rest_api) -> None:
        """Side lists are plain ordered lists"""
        response = _mount(rest_api, area=RackArea.LEFT.value)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert response.get_json()['raw']['position'] == 0

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  refusals                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMountRefusals:
    """The rules that make a mount impossible regardless of geometry"""

    def test_a_rack_can_not_be_mounted_in_a_rack(self, rest_api) -> None:
        """Any type is mountable except the Rack type - no nesting"""
        response = _mount(rest_api, object_id=OTHER_RACK_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'another Rack' in response.get_data(as_text=True)

    def test_a_rack_can_not_be_mounted_into_itself(self, rest_api) -> None:
        """The degenerate case of the same rule"""
        assert _mount(rest_api, object_id=RACK_ID).status_code == HTTPStatus.BAD_REQUEST

    def test_an_object_can_only_be_in_one_rack(self, rest_api) -> None:
        """The membership is exclusive, and the unassigned bucket counts as membership"""
        _mount(rest_api)

        response = _mount(rest_api, rack_id=OTHER_RACK_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already mounted' in response.get_data(as_text=True)

    def test_the_same_object_can_not_be_mounted_twice_in_one_rack(self, rest_api) -> None:
        """Same rule, same rack"""
        _mount(rest_api)

        assert _mount(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_mounting_into_a_non_rack_is_refused(self, rest_api) -> None:
        """An ordinary object is not a rack, so it holds nothing"""
        response = _mount(rest_api, rack_id=OTHER_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_mounting_into_a_missing_rack_is_a_404(self, rest_api) -> None:
        """No such rack"""
        assert _mount(rest_api, rack_id=999999).status_code == HTTPStatus.NOT_FOUND

    def test_mounting_a_missing_object_is_refused(self, rest_api) -> None:
        """A membership pointing at nothing would dangle immediately"""
        assert _mount(rest_api, object_id=999999).status_code == HTTPStatus.BAD_REQUEST

    def test_a_request_without_an_object_id_is_refused(self, rest_api) -> None:
        """There is nothing to mount"""
        response = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/', json={})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_area_is_refused(self, rest_api) -> None:
        """The area is a closed set"""
        assert _mount(rest_api, area='NOWHERE').status_code == HTTPStatus.BAD_REQUEST

    def test_the_payload_can_not_choose_the_rack(self, rest_api) -> None:
        """The rack comes from the URL, so a rack_id in the body is ignored"""
        response = rest_api.post(
            f'{ROUTE_URL}/{RACK_ID}/mounts/',
            json={'object_id': OBJECT_ID, 'rack_id': OTHER_RACK_ID},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert response.get_json()['raw']['rack_id'] == RACK_ID

# -------------------------------------------------------------------------------------------------------------------- #
#                                             move / resize / unplace                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateMount:
    """PATCH places, moves, resizes, reorders and unplaces"""

    def test_a_mount_can_be_reslotted(self, rest_api) -> None:
        """The mount is excluded from its own overlap check, so moving within the area works"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'start_slot': 20})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['result']['start_slot'] == 20

    def test_a_mount_keeping_its_own_slots_is_allowed(self, rest_api) -> None:
        """
        Re-sending the same geometry must not collide with itself

        Without excluding the mount under change, every no-op PATCH would fail.
        """
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))

        response = rest_api.patch(
            f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}',
            json={'area': RackArea.FRONT.value, 'start_slot': 10, 'height': 3},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_a_move_onto_occupied_slots_is_refused(self, rest_api) -> None:
        """Another mount's slots are still off limits"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=1, height=2)
        mount_id = _mount_id(_mount(rest_api, object_id=OTHER_OBJECT_ID,
                                    area=RackArea.FRONT.value, start_slot=10, height=2))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'start_slot': 1})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unplacing_frees_the_slots_and_keeps_the_height(self, rest_api) -> None:
        """The object stays a member; its height survives as a re-placing hint"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))

        response = rest_api.patch(
            f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'area': RackArea.UNASSIGNED.value},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        updated = response.get_json()['result']
        assert updated['area'] == RackArea.UNASSIGNED.value
        assert updated['start_slot'] is None
        assert updated['height'] == 3

    def test_the_freed_slots_can_be_reused(self, rest_api) -> None:
        """Unplacing really releases the range"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))
        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'area': RackArea.UNASSIGNED.value})

        response = _mount(rest_api, object_id=OTHER_OBJECT_ID,
                          area=RackArea.FRONT.value, start_slot=10, height=3)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_an_unplaced_member_can_be_placed(self, rest_api) -> None:
        """The reverse direction: from the bucket into a slot"""
        mount_id = _mount_id(_mount(rest_api))

        response = rest_api.patch(
            f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}',
            json={'area': RackArea.FRONT.value, 'start_slot': 5, 'height': 2},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['result']['start_slot'] == 5

    def test_a_side_member_can_be_reordered(self, rest_api) -> None:
        """An explicit position is honoured"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.LEFT.value))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'position': 3})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['result']['position'] == 3

    def test_patching_a_mount_of_another_rack_is_a_404(self, rest_api) -> None:
        """A mount is addressed through its own rack only"""
        mount_id = _mount_id(_mount(rest_api))

        response = rest_api.patch(f'{ROUTE_URL}/{OTHER_RACK_ID}/mounts/{mount_id}', json={'position': 1})

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_the_membership_survives_a_patch(self, rest_api) -> None:
        """A body naming another object can not re-point the mount"""
        mount_id = _mount_id(_mount(rest_api))

        response = rest_api.patch(
            f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'object_id': OTHER_OBJECT_ID},
        )

        assert response.get_json()['result']['object_id'] == OBJECT_ID

# -------------------------------------------------------------------------------------------------------------------- #
#                                              remove from rack                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteMount:
    """DELETE removes the membership and nothing else"""

    def test_the_mount_is_removed(self, rest_api) -> None:
        """After the delete the rack holds nothing"""
        mount_id = _mount_id(_mount(rest_api))

        response = rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/').get_json() == []

    def test_the_object_survives(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Un-mounting removes the reference, never the object"""
        mount_id = _mount_id(_mount(rest_api))

        rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        assert objects.find_one({'public_id': OBJECT_ID}) is not None

    def test_the_object_can_be_mounted_again_afterwards(self, rest_api) -> None:
        """The membership really went away, so a new one is allowed"""
        mount_id = _mount_id(_mount(rest_api))
        rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert _mount(rest_api, rack_id=OTHER_RACK_ID).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_deleting_a_mount_of_another_rack_is_a_404(self, rest_api) -> None:
        """Same ownership check as the PATCH"""
        mount_id = _mount_id(_mount(rest_api))

        assert rest_api.delete(
            f'{ROUTE_URL}/{OTHER_RACK_ID}/mounts/{mount_id}'
        ).status_code == HTTPStatus.NOT_FOUND

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    reads                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadMounts:
    """The listing and the where-is-this-object lookup"""

    def test_the_listing_can_be_filtered_by_area(self, rest_api) -> None:
        """?area= narrows the read to one bucket"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=1, height=1)
        _mount(rest_api, object_id=OTHER_OBJECT_ID, area=RackArea.LEFT.value)

        response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/?area={RackArea.LEFT.value}')

        assert [m['object_id'] for m in response.get_json()] == [OTHER_OBJECT_ID]

    def test_an_unknown_area_filter_is_refused(self, rest_api) -> None:
        """A typo must not silently return everything"""
        response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/?area=NOWHERE')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_listing_of_a_missing_rack_is_a_404(self, rest_api) -> None:
        """No such rack"""
        assert rest_api.get(f'{ROUTE_URL}/999999/mounts/').status_code == HTTPStatus.NOT_FOUND

    def test_where_is_this_object_returns_its_mount(self, rest_api) -> None:
        """Backs the object view, which has no other way to know it sits in a rack"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=7, height=1)

        response = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['rack_id'] == RACK_ID

    def test_where_is_this_object_is_empty_for_an_unmounted_object(self, rest_api) -> None:
        """Not being in a rack is not an error"""
        response = rest_api.get(f'{ROUTE_URL}/mounts/object/{OTHER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                              manager failure arms                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestManagerFailures:
    """
    A database failure is reported with a status rather than escaping as an unhandled exception

    Driven by patching the manager class, because the happy paths and the business-rule refusals above
    can never reach these arms. The routes carry the auth decorator stack, so they are exercised through
    a real request rather than called directly.
    """

    def test_a_failed_insert_is_a_400(self, rest_api) -> None:
        """The write itself failing is reported, not swallowed"""
        with patch.object(RackMountsManager, 'insert_item', side_effect=RackMountsManagerInsertError('boom')):
            assert _mount(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_insert_error_is_a_500(self, rest_api) -> None:
        """Anything the route did not anticipate is an internal error, not a 400"""
        with patch.object(RackMountsManager, 'insert_item', side_effect=RuntimeError('boom')):
            assert _mount(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_created_mount_that_cannot_be_read_back_is_a_404(self, rest_api) -> None:
        """A mount that vanished between the write and the read is reported, not returned as null"""
        with patch.object(RackMountsManager, 'insert_item', return_value=1), \
             patch.object(RackMountsManager, 'get_item', return_value=None):
            assert _mount(rest_api).status_code == HTTPStatus.NOT_FOUND

    def test_a_failed_listing_is_a_400(self, rest_api) -> None:
        """A failed read of the membership list is reported"""
        with patch.object(RackMountsManager, 'get_mounts_of_rack',
                          side_effect=RackMountsManagerGetError('boom')):
            assert rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/').status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_listing_error_is_a_500(self, rest_api) -> None:
        """An unanticipated read failure is an internal error"""
        with patch.object(RackMountsManager, 'get_mounts_of_rack', side_effect=RuntimeError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_failed_object_lookup_is_a_400(self, rest_api) -> None:
        """A failed where-is-this-object lookup is reported"""
        with patch.object(RackMountsManager, 'get_mount_of_object',
                          side_effect=RackMountsManagerGetError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_object_lookup_error_is_a_500(self, rest_api) -> None:
        """An unanticipated lookup failure is an internal error"""
        with patch.object(RackMountsManager, 'get_mount_of_object', side_effect=RuntimeError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_failed_update_is_a_400(self, rest_api) -> None:
        """A failed update is reported"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'update_item', side_effect=RackMountsManagerUpdateError('boom')):
            response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'position': 1})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_update_error_is_a_500(self, rest_api) -> None:
        """An unanticipated update failure is an internal error"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'update_item', side_effect=RuntimeError('boom')):
            response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'position': 1})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_failed_delete_is_a_400(self, rest_api) -> None:
        """A failed delete is reported"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'delete_item', side_effect=RackMountsManagerDeleteError('boom')):
            response = rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_delete_reporting_no_removal_is_a_400(self, rest_api) -> None:
        """A delete the manager reports as unsuccessful is not answered with a success"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'delete_item', return_value=False):
            response = rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_delete_error_is_a_500(self, rest_api) -> None:
        """An unanticipated delete failure is an internal error"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'delete_item', side_effect=RuntimeError('boom')):
            response = rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_failed_overview_read_is_a_400(self, rest_api) -> None:
        """A failed read of the rack's mounts is reported"""
        with patch.object(RackMountsManager, 'get_mounts_of_rack',
                          side_effect=RackMountsManagerGetError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_overview_error_is_a_500(self, rest_api) -> None:
        """An unanticipated failure while projecting the rack is an internal error"""
        with patch.object(RackMountsManager, 'get_mounts_of_rack', side_effect=RuntimeError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_failed_conflict_read_is_a_400(self, rest_api) -> None:
        """A failed pre-check read is reported"""
        with patch.object(RackMountsManager, 'get_mounts_in_areas',
                          side_effect=RackMountsManagerGetError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_conflict_error_is_a_500(self, rest_api) -> None:
        """An unanticipated pre-check failure is an internal error"""
        with patch.object(RackMountsManager, 'get_mounts_in_areas', side_effect=RuntimeError('boom')):
            response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_created_mount_whose_read_back_fails_is_a_400(self, rest_api) -> None:
        """A read-back failure is distinguished from the write failing"""
        with patch.object(RackMountsManager, 'insert_item', return_value=1), \
             patch.object(RackMountsManager, 'get_item', side_effect=RackMountsManagerGetError('boom')):
            assert _mount(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_an_updated_mount_that_cannot_be_read_back_is_a_404(self, rest_api) -> None:
        """A mount that vanished after the update is reported, not returned as null"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'update_item'), \
             patch.object(RackMountsManager, 'get_item', side_effect=[_stored_mount(mount_id), None]):
            response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'position': 1})

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_an_updated_mount_whose_read_back_fails_is_a_400(self, rest_api) -> None:
        """A read-back failure after the update is reported"""
        mount_id = _mount_id(_mount(rest_api))

        with patch.object(RackMountsManager, 'update_item'), \
             patch.object(RackMountsManager, 'get_item',
                          side_effect=[_stored_mount(mount_id), RackMountsManagerGetError('boom')]):
            response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}', json={'position': 1})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_refusal_from_the_object_lookup_keeps_its_status(self, rest_api) -> None:
        """
        An HTTPException raised by a helper passes through untouched

        Without the dedicated re-raise arm it would be swallowed by the generic handler and reported as
        a 500 instead of the 404 the helper chose.
        """
        response = rest_api.get(f'{ROUTE_URL}/999999/mounts/')

        assert response.status_code == HTTPStatus.NOT_FOUND

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the overview                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRackOverview:
    """GET /racks/<id>/overview returns everything needed to draw one rack"""

    def test_an_empty_rack_reports_every_area_and_the_full_free_space(self, rest_api) -> None:
        """An empty rack renders without special cases in the frontend"""
        response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert set(body['areas']) == {area.value for area in RackArea}
        assert body['total_mounts'] == 0

    def test_the_header_carries_the_racks_own_fields(self, rest_api) -> None:
        """The rack's identity comes with the overview, not from a second request"""
        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()

        assert body['rack']['public_id'] == RACK_ID
        assert body['rack']['display_name'] == 'rack-a'
        assert body['rack']['height'] == RACK_HEIGHT

    def test_a_placed_object_appears_in_its_area_with_its_summary(self, rest_api) -> None:
        """The row is resolved server-side, so the frontend needs no per-object request"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()
        rows = body['areas'][RackArea.FRONT.value]

        assert len(rows) == 1
        assert rows[0]['object_id'] == OBJECT_ID
        assert rows[0]['start_slot'] == 10
        assert rows[0]['summary_line'] is not None
        assert rows[0]['type_label'] == MEMBER_TYPE_LABEL
        assert rows[0]['type_color'] == MEMBER_TYPE_COLOR

    def test_the_legend_names_each_type_the_rack_holds_once(self, rest_api) -> None:
        """The key to the colours in the drawing: one entry per type, however many objects carry it"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=1)
        _mount(rest_api, object_id=OTHER_OBJECT_ID, area=RackArea.FRONT.value, start_slot=20, height=1)

        legend = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['types_legend']

        assert len(legend) == 1
        assert legend[0]['type_id'] == PLAIN_TYPE_ID
        assert legend[0]['type_label'] == MEMBER_TYPE_LABEL
        assert legend[0]['type_icon'] == MEMBER_TYPE_ICON
        assert legend[0]['type_color'] == MEMBER_TYPE_COLOR
        assert legend[0]['count'] == 2

    def test_the_legend_counts_unplaced_members_too(self, rest_api) -> None:
        """It follows membership, not placement"""
        _mount(rest_api)

        legend = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['types_legend']

        assert [entry['count'] for entry in legend] == [1]

    def test_the_legend_excludes_the_racks_own_type(self, rest_api) -> None:
        """The rack is the container, not content - and a Rack can not be mounted inside a Rack anyway"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=1)

        legend = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['types_legend']

        assert RACK_TYPE_ID not in [entry['type_id'] for entry in legend]

    def test_an_empty_rack_has_an_empty_legend(self, rest_api) -> None:
        """An empty list rather than nothing, so the frontend renders it without a special case"""
        assert rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['types_legend'] == []

    def test_the_overview_reports_no_free_slots(self, rest_api) -> None:
        """
        Which slots are free is deliberately not the backend's answer

        The frontend draws the rack from the buckets, so occupancy is visible there; whether a specific
        placement is allowed comes from the pre-validation route instead.
        """
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=2, height=2)

        assert 'free_slots' not in rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()

    def test_an_unplaced_member_appears_in_the_unassigned_bucket(self, rest_api) -> None:
        """Membership without placement is still membership"""
        _mount(rest_api)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()

        assert [r['object_id'] for r in body['areas'][RackArea.UNASSIGNED.value]] == [OBJECT_ID]
        assert body['total_mounts'] == 1

    def test_a_main_area_bucket_comes_out_slot_ordered(self, rest_api) -> None:
        """A main area has no position index - its slots are its order"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=1)
        _mount(rest_api, object_id=OTHER_OBJECT_ID, area=RackArea.FRONT.value, start_slot=5, height=1)

        rows = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['areas'][RackArea.FRONT.value]

        assert [r['start_slot'] for r in rows] == [5, 20]

    def test_the_overview_of_a_missing_rack_is_a_404(self, rest_api) -> None:
        """No such rack"""
        assert rest_api.get(f'{ROUTE_URL}/999999/overview').status_code == HTTPStatus.NOT_FOUND

    def test_the_overview_of_a_non_rack_is_a_400(self, rest_api) -> None:
        """An ordinary object has no layout"""
        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID}/overview').status_code == HTTPStatus.BAD_REQUEST

# -------------------------------------------------------------------------------------------------------------------- #
#                                            the shrink pre-check                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHeightConflicts:
    """GET /racks/<id>/height_conflicts answers "what would a smaller rack displace?\""""

    def test_a_height_that_fits_everything_reports_nothing(self, rest_api) -> None:
        """Shrinking to exactly the anchor displaces nothing - the boundary is inclusive"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=2)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10').get_json()

        assert body['total'] == 0
        assert body['conflicts'] == []
        assert body['height'] == 10

    def test_a_mount_beyond_the_new_height_is_reported_with_its_summary(self, rest_api) -> None:
        """The dialog needs to name the objects, so the rows are resolved like the overview's"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10').get_json()

        assert body['total'] == 1
        assert body['conflicts'][0]['object_id'] == OBJECT_ID
        assert body['conflicts'][0]['summary_line'] is not None

    def test_the_pre_check_writes_nothing(self, rest_api) -> None:
        """It only answers a question - the height change is what displaces the mounts"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2))

        rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10')

        rows = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/').get_json()
        unchanged = next(row for row in rows if row['public_id'] == mount_id)
        assert unchanged['area'] == RackArea.FRONT.value
        assert unchanged['start_slot'] == 20

    def test_an_unplaced_member_is_never_a_conflict(self, rest_api) -> None:
        """It holds no slots, so no height can push it out"""
        _mount(rest_api)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=1').get_json()

        assert body['total'] == 0

    @pytest.mark.parametrize('query', ['', '?height=', '?height=0', '?height=-2', '?height=abc'])
    def test_a_missing_or_unusable_height_is_a_400(self, rest_api, query: str) -> None:
        """A rack height is a positive whole number here too"""
        response = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts{query}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_pre_check_of_a_missing_rack_is_a_404(self, rest_api) -> None:
        """No such rack"""
        response = rest_api.get(f'{ROUTE_URL}/999999/height_conflicts?height=10')

        assert response.status_code == HTTPStatus.NOT_FOUND

# -------------------------------------------------------------------------------------------------------------------- #
#                                        the shrink hook on the object write                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHeightShrinkOnObjectWrite:
    """
    Lowering a Rack's height unplaces what no longer fits

    The height is an ordinary field, so it is changed through /objects - which is exactly why the rule
    lives on the object write path and not only in the rack routes. Nothing is deleted: the objects stay
    members and keep their height, so re-placing them is one call.
    """

    @staticmethod
    def _rack_payload(height: int) -> dict[str, Any]:
        """The full Rack CmdbObject payload PUT /objects/<id> expects"""
        return {
            'public_id': RACK_ID,
            'type_id': RACK_TYPE_ID,
            'active': True,
            'author_id': SEED_AUTHOR_ID,
            'version': SEED_VERSION,
            'fields': [
                {'type': 'text', 'name': RackField.NAME.value, 'value': 'rack-a'},
                {'type': 'number', 'name': RackField.HEIGHT.value, 'value': height},
            ],
        }

    def _set_height(self, rest_api, height: int):
        """Changes the rack's height through the ordinary object update route"""
        return rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=self._rack_payload(height))

    def test_shrinking_unplaces_the_mounts_that_no_longer_fit(self, rest_api) -> None:
        """The mount at U20 cannot survive a 10U rack"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2))

        assert self._set_height(rest_api, 10).status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        moved = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()
        assert moved['public_id'] == mount_id
        assert moved['area'] == RackArea.UNASSIGNED.value
        assert moved['start_slot'] is None

    def test_the_displaced_object_keeps_its_height_as_a_hint(self, rest_api) -> None:
        """The height is the tedious value to re-enter, so re-placing can pre-fill it"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=3)

        self._set_height(rest_api, 10)

        assert rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()['height'] == 3

    def test_the_displaced_object_stays_a_member_of_the_rack(self, rest_api) -> None:
        """Unplacing is not removal - nothing is lost"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2)

        self._set_height(rest_api, 10)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()
        assert body['total_mounts'] == 1
        assert len(body['areas'][RackArea.UNASSIGNED.value]) == 1

    def test_the_mounts_that_still_fit_are_untouched(self, rest_api) -> None:
        """A shrink is not a reset"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=2, height=2)
        _mount(rest_api, object_id=OTHER_OBJECT_ID, area=RackArea.FRONT.value, start_slot=20, height=2)

        self._set_height(rest_api, 10)

        kept = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()
        assert kept['area'] == RackArea.FRONT.value
        assert kept['start_slot'] == 2

    def test_a_mount_anchored_exactly_at_the_new_top_survives(self, rest_api) -> None:
        """The boundary is inclusive"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=2)

        self._set_height(rest_api, 10)

        assert rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()['area'] == RackArea.FRONT.value

    def test_growing_the_rack_displaces_nothing(self, rest_api) -> None:
        """More room cannot push anything out"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2)

        self._set_height(rest_api, 60)

        assert rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()['area'] == RackArea.FRONT.value

    def test_the_freed_slots_become_available_again(self, rest_api) -> None:
        """The displacement really releases the range, within the new smaller rack"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        self._set_height(rest_api, 9)

        response = _mount(rest_api, object_id=OTHER_OBJECT_ID,
                          area=RackArea.FRONT.value, start_slot=9, height=3)
        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_the_pre_check_predicted_what_the_write_did(self, rest_api) -> None:
        """
        The dialog's warning and the actual outcome come from the same computation

        If these could disagree the user would be told one thing and get another.
        """
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2)

        predicted = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=10').get_json()
        predicted_ids = sorted(row['mount_id'] for row in predicted['conflicts'])

        self._set_height(rest_api, 10)

        body = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()
        actual_ids = sorted(row['mount_id'] for row in body['areas'][RackArea.UNASSIGNED.value])

        assert predicted_ids == actual_ids

    def test_a_displaced_object_can_be_re_placed_into_the_smaller_rack(self, rest_api) -> None:
        """The whole point of unplacing rather than deleting"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2))
        self._set_height(rest_api, 10)

        response = rest_api.patch(
            f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}',
            json={'area': RackArea.FRONT.value, 'start_slot': 2, 'height': 2},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['result']['start_slot'] == 2

    def test_editing_a_rack_without_touching_the_height_changes_no_layout(self, rest_api) -> None:
        """An ordinary edit must not disturb the mounts"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=20, height=2)

        payload = self._rack_payload(RACK_HEIGHT)
        payload['fields'][0]['value'] = 'rack-a-renamed'
        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=payload)

        kept = rest_api.get(f'{ROUTE_URL}/mounts/object/{OBJECT_ID}').get_json()
        assert kept['area'] == RackArea.FRONT.value
        assert kept['start_slot'] == 20

    def test_shrinking_a_rack_with_nothing_placed_is_harmless(self, rest_api) -> None:
        """No mounts, nothing to displace"""
        _mount(rest_api)

        assert self._set_height(rest_api, 5).status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()['total_mounts'] == 1

# -------------------------------------------------------------------------------------------------------------------- #
#                                            the dry-run validate route                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateMount:
    """
    POST /racks/<id>/mounts/validate answers "would this be accepted?" without writing

    The dry run behind a drag-and-drop. It runs the same checks the write runs, so the two can never
    disagree - and it names the blocker so the UI can say why rather than just no.
    """

    def _validate(self, rest_api, **body: Any):
        """POSTs a candidate to the pre-validation route"""
        payload: dict[str, Any] = {'object_id': OBJECT_ID}
        payload.update(body)

        return rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate', json=payload)

    def test_a_valid_placement_is_accepted(self, rest_api) -> None:
        """The happy path answers valid with no reasons"""
        response = self._validate(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'valid': True, 'errors': []}

    def test_a_bare_candidate_is_accepted(self, rest_api) -> None:
        """No area means "assign without placing", which the write would accept too"""
        assert self._validate(rest_api).get_json()['valid'] is True

    def test_it_writes_nothing(self, rest_api) -> None:
        """
        The whole point of the dry run

        It is called while the user is still dragging, so it must be safe to call repeatedly.
        """
        self._validate(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        assert rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/').get_json() == []

    def test_an_occupied_slot_is_rejected_naming_the_blocking_mount(self, rest_api) -> None:
        """The reason is what makes this more useful than a boolean"""
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))

        body = self._validate(rest_api, object_id=OTHER_OBJECT_ID,
                              area=RackArea.FRONT.value, start_slot=10, height=2).get_json()

        assert body['valid'] is False
        assert str(mount_id) in body['errors'][0]['message']
        assert '[9, 10]' in body['errors'][0]['message']

    def test_a_mount_above_the_rack_is_rejected(self, rest_api) -> None:
        """Same fit rules as the write"""
        body = self._validate(rest_api, area=RackArea.FRONT.value, start_slot=43, height=1).get_json()

        assert body['valid'] is False
        assert 'above the Rack height' in body['errors'][0]['message']

    def test_a_mount_below_the_rack_floor_is_rejected(self, rest_api) -> None:
        """A mount grows downward, so it can leave the rack at the bottom too"""
        body = self._validate(rest_api, area=RackArea.FRONT.value, start_slot=2, height=4).get_json()

        assert body['valid'] is False
        assert 'below the bottom' in body['errors'][0]['message']

    def test_a_missing_geometry_is_rejected(self, rest_api) -> None:
        """A main-area placement needs a start slot and a height"""
        body = self._validate(rest_api, area=RackArea.FRONT.value).get_json()

        assert body['valid'] is False
        assert len(body['errors']) == 2

    def test_an_already_mounted_object_is_rejected(self, rest_api) -> None:
        """The membership rule is checked too - something free_slots never covered"""
        _mount(rest_api)

        body = self._validate(rest_api, rack_id=RACK_ID).get_json()

        assert body['valid'] is False
        assert 'already mounted' in body['errors'][0]['message']

    def test_another_rack_is_rejected(self, rest_api) -> None:
        """Racks do not nest, and the dry run says so before the drop"""
        body = self._validate(rest_api, object_id=OTHER_RACK_ID).get_json()

        assert body['valid'] is False
        assert 'another Rack' in body['errors'][0]['message']

    def test_a_missing_object_id_is_rejected(self, rest_api) -> None:
        """There is nothing to validate"""
        response = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate', json={})

        assert response.get_json()['valid'] is False

    def test_a_membership_problem_hides_the_geometry_answer(self, rest_api) -> None:
        """
        An object that may not be mounted at all has no meaningful geometry answer

        Reporting one would bury the real problem.
        """
        body = self._validate(rest_api, object_id=OTHER_RACK_ID,
                              area=RackArea.FRONT.value, start_slot=99, height=99).get_json()

        assert len(body['errors']) == 1
        assert 'another Rack' in body['errors'][0]['message']

    def test_validating_a_move_excludes_the_mount_itself(self, rest_api) -> None:
        """
        Without mount_id, re-validating a mount's own slots would collide with itself

        This is the drag-and-drop of an object that is already in the rack.
        """
        mount_id = _mount_id(_mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3))

        body = self._validate(rest_api, mount_id=mount_id,
                              area=RackArea.FRONT.value, start_slot=10, height=3).get_json()

        assert body['valid'] is True

    def test_validating_a_move_still_reports_another_mounts_slots(self, rest_api) -> None:
        """The exclusion is one specific mount, not a free pass"""
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=4, height=2)
        mount_id = _mount_id(_mount(rest_api, object_id=OTHER_OBJECT_ID,
                                    area=RackArea.FRONT.value, start_slot=10, height=2))

        body = self._validate(rest_api, object_id=OTHER_OBJECT_ID, mount_id=mount_id,
                              area=RackArea.FRONT.value, start_slot=4, height=2).get_json()

        assert body['valid'] is False

    def test_the_answer_agrees_with_what_the_write_does(self, rest_api) -> None:
        """
        The reason the dry run exists rather than the frontend computing it

        Every candidate is checked twice - once as a dry run, once for real - and the two must agree.
        """
        _mount(rest_api, area=RackArea.FRONT.value, start_slot=10, height=3)

        candidates: list[dict[str, Any]] = [
            {'area': RackArea.FRONT.value, 'start_slot': 10, 'height': 1},   # occupied
            {'area': RackArea.FRONT.value, 'start_slot': 8, 'height': 1},    # free
            {'area': RackArea.BACK.value, 'start_slot': 10, 'height': 1},    # free (other view)
            {'area': RackArea.FULL_DEPTH.value, 'start_slot': 9, 'height': 1},  # blocked by the front mount
            {'area': RackArea.FRONT.value, 'start_slot': 43, 'height': 1},   # above the rack
            {'area': RackArea.LEFT.value},                                    # side, always fine
        ]

        for candidate in candidates:
            dry_run = self._validate(rest_api, object_id=OTHER_OBJECT_ID, **candidate).get_json()['valid']
            written = _mount(rest_api, object_id=OTHER_OBJECT_ID, **candidate)
            accepted = written.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

            assert dry_run == accepted, f'{candidate} - dry run said {dry_run}, the write said {accepted}'

            if accepted:
                rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{_mount_id(written)}')

    def test_validating_against_a_missing_rack_is_a_404(self, rest_api) -> None:
        """No such rack to validate against"""
        response = rest_api.post(f'{ROUTE_URL}/999999/mounts/validate', json={'object_id': OBJECT_ID})

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_validating_against_a_non_rack_is_a_400(self, rest_api) -> None:
        """An ordinary object holds nothing"""
        response = rest_api.post(f'{ROUTE_URL}/{OTHER_OBJECT_ID}/mounts/validate',
                                 json={'object_id': OBJECT_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_read_is_a_400(self, rest_api) -> None:
        """A database failure is reported, not escaped"""
        with patch.object(RackMountsManager, 'is_object_mounted',
                          side_effect=RackMountsManagerGetError('boom')):
            response = self._validate(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_error_is_a_500(self, rest_api) -> None:
        """An unanticipated failure is an internal error"""
        with patch.object(RackMountsManager, 'is_object_mounted', side_effect=RuntimeError('boom')):
            response = self._validate(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

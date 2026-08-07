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
Functional tests for Rack reservations and blockers, over the REST routes

An occupant is a row in the rack that names no CmdbObject: a RESERVATION holds space for hardware that
will arrive later, a BLOCKER marks space that can not be mounted at all. They share the mount's document,
its route and its overlap check - only the kind and the fields each may carry differ.

Walked end to end here: creating both kinds, several blockers in one rack (which is what the partial
unique index buys), that an occupant blocks a mount and a mount blocks an occupant, that unassigning and
deleting both free the slots again, the per-kind field refusals, that the kind of a row can not be
changed, and that no location node is ever created for an occupant
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKind
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/racks'
OBJECTS_URL: str = '/objects'

RACK_TYPE_ID: int = 9751
PLAIN_TYPE_ID: int = 9752

RACK_ID: int = 9761
OBJECT_ID: int = 9771

RACK_HEIGHT: int = 42
PLAIN_FIELD: str = 'plain-field'
LOCATION_FIELD: str = 'dg_location'

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [RACK_ID, OBJECT_ID]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

COLOR: str = '#4CAF50'
START_DATE: str = '2026-09-01T00:00:00+00:00'
END_DATE: str = '2026-09-30T00:00:00+00:00'


def _rack_type_doc() -> dict[str, Any]:
    """The Rack CmdbType"""
    return {
        'public_id': RACK_TYPE_ID,
        'name': 'rack-occupant-type',
        'label': 'Rack',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
            {'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-server',
            'sections': [{
                'type': 'section',
                'name': RackSection.INFORMATION.value,
                'label': 'Information',
                'fields': [RackField.NAME.value, RackField.HEIGHT.value, LOCATION_FIELD],
            }],
            'summary': {'fields': [RackField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _plain_type_doc() -> dict[str, Any]:
    """A mountable CmdbType - it declares a location field, as every rack member's type must"""
    return {
        'public_id': PLAIN_TYPE_ID,
        'name': 'rack-occupant-member',
        'label': 'Member',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': PLAIN_FIELD, 'label': 'Plain'},
            {'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [PLAIN_FIELD, LOCATION_FIELD]}],
            'summary': {'fields': [PLAIN_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _rack_doc() -> dict[str, Any]:
    """The Rack CmdbObject the occupants are placed in"""
    return {
        'public_id': RACK_ID,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'value': 'rack-a'},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'value': RACK_HEIGHT},
            {'type': 'location', 'name': LOCATION_FIELD, 'value': None},
        ],
    }


def _member_doc() -> dict[str, Any]:
    """A mountable CmdbObject"""
    return {
        'public_id': OBJECT_ID,
        'type_id': PLAIN_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': 'text', 'name': PLAIN_FIELD, 'value': 'server-01'},
            {'type': 'location', 'name': LOCATION_FIELD, 'value': None},
        ],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Rack type and one mountable type for the module"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    types.insert_many([_rack_type_doc(), _plain_type_doc()])

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds one rack and one mountable object, and clears every row around each test

    The declared indexes are built here because the test database never goes through
    CollectionValidator - without it the partial unique index would not exist and the several-blockers
    assertions would pass on a collection with no constraint at all.
    """
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    mounts = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)

    database_manager.create_indexes(
        CmdbRackMount.COLLECTION, database_name, CmdbRackMount.get_index_keys(),
    )

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})
    mounts.delete_many({'rack_id': RACK_ID})
    objects.insert_many([_rack_doc(), _member_doc()])

    yield objects, locations, mounts

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})
    mounts.delete_many({'rack_id': RACK_ID})


def _create(rest_api, kind: str, **body: Any):
    """POSTs a row of the given kind to the rack"""
    payload: dict[str, Any] = {'kind': kind}
    payload.update(body)

    return rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/', json=payload)


def _blocker(rest_api, start_slot: int = 20, height: int = 2,
             area: str = RackArea.FRONT.value, **body: Any):
    """Creates a blocker occupying a U range"""
    return _create(rest_api, RackMountKind.BLOCKER.value,
                   area=area, start_slot=start_slot, height=height, **body)


def _reservation(rest_api, start_slot: int = 30, height: int = 3,
                 area: str = RackArea.FRONT.value, **body: Any):
    """Creates a reservation occupying a U range"""
    return _create(rest_api, RackMountKind.RESERVATION.value,
                   area=area, start_slot=start_slot, height=height, **body)


def _mount(rest_api, start_slot: int = 10, height: int = 1, **body: Any):
    """Mounts the member object"""
    payload: dict[str, Any] = {'object_id': OBJECT_ID, 'area': RackArea.FRONT.value,
                               'start_slot': start_slot, 'height': height}
    payload.update(body)

    return rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/', json=payload)


def _row_id(response) -> int:
    """The created row's public_id"""
    return response.get_json()['result_id']


def _rows(rest_api) -> list[dict[str, Any]]:
    """Every row of the rack"""
    return rest_api.get(f'{ROUTE_URL}/{RACK_ID}/mounts/').get_json()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              creating occupants                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreatingOccupants:
    """A reservation and a blocker are created through the same route a mount is"""

    def test_a_blocker_is_created(self, rest_api) -> None:
        """The metal frame between two rack sections"""
        response = _blocker(rest_api, label='Metal frame')

        assert response.status_code == HTTPStatus.CREATED
        assert response.get_json()['raw']['kind'] == RackMountKind.BLOCKER.value
        assert response.get_json()['raw']['label'] == 'Metal frame'

    def test_a_blocker_names_no_object(self, rest_api) -> None:
        """
        The key is OMITTED, not stored as null

        A stored null would still be indexed by the partial unique index, so the second blocker in the
        collection would be refused with a duplicate-key error.
        """
        assert 'object_id' not in _blocker(rest_api).get_json()['raw']

    def test_a_reservation_carries_its_dates_and_colour(self, rest_api) -> None:
        """The three fields a reservation adds"""
        raw = _reservation(rest_api, start_date=START_DATE, end_date=END_DATE, color=COLOR,
                           label='Reserved for DB cluster').get_json()['raw']

        assert raw['kind'] == RackMountKind.RESERVATION.value
        assert raw['color'] == COLOR
        assert raw['label'] == 'Reserved for DB cluster'
        assert raw['start_date'] is not None
        assert raw['end_date'] is not None

    def test_a_reservation_needs_none_of_its_fields(self, rest_api) -> None:
        """All three are optional - a bare reservation is a valid reservation"""
        assert _reservation(rest_api).status_code == HTTPStatus.CREATED

    def test_several_blockers_fit_in_one_rack(self, rest_api) -> None:
        """
        What the partial unique index buys

        Every occupant omits object_id, and a unique index treats each missing value as the same null -
        so without the partial filter the SECOND blocker anywhere in the installation would be refused.
        """
        assert _blocker(rest_api, start_slot=20, height=2).status_code == HTTPStatus.CREATED
        assert _blocker(rest_api, start_slot=15, height=2).status_code == HTTPStatus.CREATED
        assert _blocker(rest_api, start_slot=5, height=1).status_code == HTTPStatus.CREATED

        assert len(_rows(rest_api)) == 3

    def test_blockers_and_reservations_coexist(self, rest_api) -> None:
        """Both kinds, and a mount, in the same rack"""
        _blocker(rest_api, start_slot=20, height=2)
        _reservation(rest_api, start_slot=30, height=3)
        _mount(rest_api, start_slot=10, height=1)

        kinds = sorted(row['kind'] for row in _rows(rest_api))
        assert kinds == [RackMountKind.BLOCKER.value, RackMountKind.MOUNT.value,
                         RackMountKind.RESERVATION.value]

    def test_a_mount_still_defaults_to_the_mount_kind(self, rest_api) -> None:
        """A client that predates the reservations keeps working unchanged"""
        assert _mount(rest_api).get_json()['raw']['kind'] == RackMountKind.MOUNT.value

# -------------------------------------------------------------------------------------------------------------------- #
#                                          occupants hold their slots                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestOccupantsBlockTheSlots:
    """An object can not be placed where a reservation or a blocker sits, and the reverse"""

    def test_a_mount_over_a_blocker_is_refused(self, rest_api) -> None:
        """The user has to remove the blocker first - that is the whole point of one"""
        _blocker(rest_api, start_slot=20, height=2)

        response = _mount(rest_api, start_slot=20, height=1)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'occupied' in response.get_data(as_text=True)

    def test_a_mount_over_a_reservation_is_refused(self, rest_api) -> None:
        """Same rule - a reservation holds the space until somebody releases it"""
        _reservation(rest_api, start_slot=30, height=3)

        assert _mount(rest_api, start_slot=29, height=1).status_code == HTTPStatus.BAD_REQUEST

    def test_an_occupant_over_a_mount_is_refused(self, rest_api) -> None:
        """The rule is symmetric: an occupant can not be dropped onto a mounted object either"""
        _mount(rest_api, start_slot=10, height=2)

        assert _blocker(rest_api, start_slot=10, height=1).status_code == HTTPStatus.BAD_REQUEST

    def test_two_occupants_may_not_overlap(self, rest_api) -> None:
        """They compete for the same U range as anything else does"""
        _blocker(rest_api, start_slot=20, height=3)

        assert _reservation(rest_api, start_slot=19, height=1).status_code == HTTPStatus.BAD_REQUEST

    def test_an_occupant_in_the_back_does_not_block_the_front(self, rest_api) -> None:
        """The area rules are the mount's rules - a blocker is not implicitly full depth"""
        _blocker(rest_api, start_slot=20, height=2, area=RackArea.BACK.value)

        assert _mount(rest_api, start_slot=20, height=2).status_code == HTTPStatus.CREATED

    def test_a_full_depth_blocker_blocks_both_views(self, rest_api) -> None:
        """And it can be full depth when the frame really does run through the rack"""
        _create(rest_api, RackMountKind.BLOCKER.value,
                area=RackArea.FULL_DEPTH.value, start_slot=20, height=2)

        assert _mount(rest_api, start_slot=20, height=1).status_code == HTTPStatus.BAD_REQUEST
        assert _mount(rest_api, start_slot=20, height=1,
                      area=RackArea.BACK.value).status_code == HTTPStatus.BAD_REQUEST

    def test_the_dry_run_reports_an_occupied_slot(self, rest_api) -> None:
        """The pre-check behind a drag-and-drop answers before the drop"""
        _blocker(rest_api, start_slot=20, height=2)

        body = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate',
                             json={'object_id': OBJECT_ID, 'area': RackArea.FRONT.value,
                                   'start_slot': 20, 'height': 1}).get_json()

        assert body['valid'] is False

    def test_the_dry_run_accepts_an_occupant_candidate(self, rest_api) -> None:
        """An occupant validates without an object_id, the way it is created"""
        body = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate',
                             json={'kind': RackMountKind.BLOCKER.value, 'area': RackArea.FRONT.value,
                                   'start_slot': 20, 'height': 2}).get_json()

        assert body == {'valid': True, 'errors': []}

    def test_the_dry_run_rejects_an_unknown_kind(self, rest_api) -> None:
        """It runs the same guards the write does, so it can not accept a row the write refuses"""
        body = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate',
                             json={'kind': 'RESERVATON'}).get_json()

        assert body['valid'] is False

    def test_the_dry_run_rejects_a_wrong_shaped_row(self, rest_api) -> None:
        """
        And it reports the shape reason rather than a geometry one

        A row carrying the wrong fields for its kind has no meaningful placement answer, so reporting
        one would bury the real problem.
        """
        body = rest_api.post(f'{ROUTE_URL}/{RACK_ID}/mounts/validate',
                             json={'kind': RackMountKind.BLOCKER.value, 'color': COLOR,
                                   'area': RackArea.FRONT.value, 'start_slot': 20,
                                   'height': 2}).get_json()

        assert body['valid'] is False
        assert 'color' in body['errors'][0]['message']

# -------------------------------------------------------------------------------------------------------------------- #
#                                            releasing the slots                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReleasingTheSlots:
    """A user removes or unassigns the occupant before an object can go there"""

    def test_deleting_a_blocker_frees_its_slots(self, rest_api) -> None:
        """The 'delete' half of "delete or unassign" """
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))
        assert _mount(rest_api, start_slot=20, height=1).status_code == HTTPStatus.BAD_REQUEST

        rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}')

        assert _mount(rest_api, start_slot=20, height=1).status_code == HTTPStatus.CREATED

    def test_unassigning_a_blocker_frees_its_slots(self, rest_api) -> None:
        """The 'unassign' half - the blocker stays in the rack, holding nothing"""
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))

        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        assert _mount(rest_api, start_slot=20, height=1).status_code == HTTPStatus.CREATED

    def test_an_unassigned_occupant_stays_in_the_rack(self, rest_api) -> None:
        """Which is what makes the bucket read as a "still needs re-placing" list"""
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))

        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        rows = _rows(rest_api)
        assert len(rows) == 1
        assert rows[0]['area'] == RackArea.UNASSIGNED.value
        assert rows[0]['kind'] == RackMountKind.BLOCKER.value

    def test_an_unassigned_occupant_can_be_placed_again(self, rest_api) -> None:
        """The way back out of the bucket"""
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))
        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                                  json={'area': RackArea.FRONT.value, 'start_slot': 25, 'height': 2})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _mount(rest_api, start_slot=25, height=1).status_code == HTTPStatus.BAD_REQUEST

    def test_a_shrink_unassigns_an_occupant_that_no_longer_fits(self, rest_api) -> None:
        """Exactly what it does to a mount - the occupant is displaced, never deleted"""
        _blocker(rest_api, start_slot=40, height=2)

        payload = _rack_doc()
        payload.pop('creation_time')
        payload['fields'][1]['value'] = 20
        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=payload)

        rows = _rows(rest_api)
        assert len(rows) == 1
        assert rows[0]['area'] == RackArea.UNASSIGNED.value
        assert rows[0]['height'] == 2

# -------------------------------------------------------------------------------------------------------------------- #
#                                            the per-kind field rules                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheFieldRules:
    """A row carrying a field its kind does not own is refused, not silently trimmed"""

    def test_an_occupant_naming_an_object_is_refused(self, rest_api) -> None:
        """Naming an object would make it a mount by another name"""
        response = _blocker(rest_api, object_id=OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'object_id' in response.get_data(as_text=True)

    def test_a_mount_carrying_a_reservation_field_is_refused(self, rest_api) -> None:
        """A client that gets a colourless mount back would have no way to notice it was dropped"""
        response = _mount(rest_api, color=COLOR)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'color' in response.get_data(as_text=True)

    def test_a_blocker_carrying_dates_is_refused(self, rest_api) -> None:
        """A blocker is a fact about the rack, not a plan"""
        assert _blocker(rest_api, start_date=START_DATE).status_code == HTTPStatus.BAD_REQUEST

    def test_a_malformed_colour_is_refused(self, rest_api) -> None:
        """One spelling only, so a frontend never has to guess how to render a stored colour"""
        response = _reservation(rest_api, color='red')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'RRGGBB' in response.get_data(as_text=True)

    def test_an_unusable_date_is_refused(self, rest_api) -> None:
        """Refused rather than dropped"""
        assert _reservation(rest_api, start_date='01.09.2026 or so').status_code == \
            HTTPStatus.BAD_REQUEST

    def test_an_end_before_the_start_is_refused(self, rest_api) -> None:
        """The one cross-field rule the dates have"""
        response = _reservation(rest_api, start_date=END_DATE, end_date=START_DATE)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'end_date' in response.get_data(as_text=True)

    def test_one_date_alone_is_accepted(self, rest_api) -> None:
        """Both ends are optional, so only a range given in full can be inverted"""
        assert _reservation(rest_api, start_date=START_DATE).status_code == HTTPStatus.CREATED

    def test_a_long_expired_reservation_is_accepted_and_still_blocks(self, rest_api) -> None:
        """
        The dates are descriptive - nothing reads the clock

        A reservation holds its slots until somebody deletes or unassigns it, whatever its dates say.
        """
        _reservation(rest_api, start_slot=30, height=3,
                     start_date='2001-01-01T00:00:00+00:00', end_date='2001-02-01T00:00:00+00:00')

        assert _mount(rest_api, start_slot=30, height=1).status_code == HTTPStatus.BAD_REQUEST

    def test_an_occupant_in_a_side_list_is_refused(self, rest_api) -> None:
        """A side list carries no geometry, so a blocker there would block nothing"""
        response = _create(rest_api, RackMountKind.BLOCKER.value, area=RackArea.LEFT.value)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_kind_is_refused(self, rest_api) -> None:
        """Refused rather than defaulted to MOUNT - a misspelling must not create the wrong row"""
        response = _create(rest_api, 'RESERVATON', area=RackArea.FRONT.value, start_slot=5, height=1)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_patch_may_edit_a_reservations_descriptive_fields(self, rest_api) -> None:
        """Its label, dates and colour are each editable without re-sending the geometry"""
        reservation_id = _row_id(_reservation(rest_api, color=COLOR))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{reservation_id}',
                                  json={'color': '#FF9800', 'label': 'moved to Q4'})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['result']['color'] == '#FF9800'
        assert response.get_json()['result']['label'] == 'moved to Q4'

    def test_a_patch_is_judged_against_the_stored_dates(self, rest_api) -> None:
        """Moving only the end date is still checked against the start date already stored"""
        reservation_id = _row_id(_reservation(rest_api, start_date=START_DATE, end_date=END_DATE))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{reservation_id}',
                                  json={'end_date': '2026-08-01T00:00:00+00:00'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_kind_of_a_row_can_not_be_changed(self, rest_api) -> None:
        """
        A reservation may cover space for several future devices

        So it is not a 1:1 promise to one object and there is nothing to convert - it is deleted, then
        the object is mounted.
        """
        reservation_id = _row_id(_reservation(rest_api))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{reservation_id}',
                                  json={'kind': RackMountKind.MOUNT.value})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_patch_echoing_the_same_kind_is_allowed(self, rest_api) -> None:
        """A client that sends the whole row back must not be refused for what is already stored"""
        reservation_id = _row_id(_reservation(rest_api))

        response = rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{reservation_id}',
                                  json={'kind': RackMountKind.RESERVATION.value, 'label': 'still here'})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

# -------------------------------------------------------------------------------------------------------------------- #
#                                        occupants are not in the location tree                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestOccupantsStayOutOfTheTree:
    """The tree mirrors CmdbObjects, and an occupant names none"""

    def _place_rack(self, rest_api, locations) -> None:
        """Gives the rack a location, so a member of it WOULD get a node"""
        locations.insert_one({
            'public_id': 9791, 'name': 'Datacenter', 'parent': 1, 'object_id': 9792,
            'type_id': RACK_TYPE_ID, 'type_label': 'Datacenter', 'type_icon': 'fa-building',
            'type_selectable': True,
        })
        payload = _rack_doc()
        payload.pop('creation_time')
        payload['fields'][2]['value'] = 9791
        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=payload)

    def test_a_blocker_gets_no_location_node(self, rest_api, collections) -> None:
        """There is no object to hang anywhere"""
        _, locations, _ = collections
        self._place_rack(rest_api, locations)
        before: int = locations.count_documents({})

        _blocker(rest_api)

        assert locations.count_documents({}) == before
        locations.delete_many({'public_id': 9791})

    def test_a_reservation_gets_no_location_node(self, rest_api, collections) -> None:
        """Same for the other kind"""
        _, locations, _ = collections
        self._place_rack(rest_api, locations)
        before: int = locations.count_documents({})

        _reservation(rest_api)

        assert locations.count_documents({}) == before
        locations.delete_many({'public_id': 9791})

    def test_deleting_an_occupant_touches_no_location(self, rest_api, collections) -> None:
        """It never had a node to remove, so the delete hook must not go looking for one"""
        _, locations, _ = collections
        self._place_rack(rest_api, locations)
        blocker_id = _row_id(_blocker(rest_api))
        before: int = locations.count_documents({})

        response = rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert locations.count_documents({}) == before
        locations.delete_many({'public_id': 9791})

    def test_a_mounted_object_still_gets_its_node(self, rest_api, collections) -> None:
        """The guard must not have switched the mirroring off for everything"""
        _, locations, _ = collections
        self._place_rack(rest_api, locations)

        _mount(rest_api)

        assert locations.find_one({'object_id': OBJECT_ID}) is not None
        locations.delete_many({'public_id': 9791})

# -------------------------------------------------------------------------------------------------------------------- #
#                                        the overview draws the occupants                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheOverview:
    """The grid is drawn from the overview, so every occupant has to reach it fully formed"""

    def _overview(self, rest_api) -> dict[str, Any]:
        """GETs the rack overview"""
        return rest_api.get(f'{ROUTE_URL}/{RACK_ID}/overview').get_json()

    def _row(self, rest_api, area: str, mount_id: int) -> dict[str, Any]:
        """One row of an area bucket, by its mount id"""
        return next(row for row in self._overview(rest_api)['areas'][area]
                    if row['mount_id'] == mount_id)

    def test_a_blocker_is_drawn_with_its_kind_and_label(self, rest_api) -> None:
        """The grid switches on `kind` rather than guessing from which fields are null"""
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2, label='Metal frame'))

        row = self._row(rest_api, RackArea.FRONT.value, blocker_id)

        assert row['kind'] == RackMountKind.BLOCKER.value
        assert row['label'] == 'Metal frame'
        assert row['start_slot'] == 20
        assert row['height'] == 2

    def test_a_reservation_is_drawn_with_its_dates_and_colour(self, rest_api) -> None:
        """Everything the grid needs to style a reservation differently from a blocker"""
        reservation_id = _row_id(_reservation(rest_api, start_date=START_DATE, end_date=END_DATE,
                                              color=COLOR, label='Reserved for DB cluster'))

        row = self._row(rest_api, RackArea.FRONT.value, reservation_id)

        assert row['kind'] == RackMountKind.RESERVATION.value
        assert row['color'] == COLOR
        assert row['label'] == 'Reserved for DB cluster'
        assert row['start_date'] is not None
        assert row['end_date'] is not None

    def test_an_occupant_row_names_no_object(self, rest_api) -> None:
        """It occupies the rack without being one"""
        blocker_id = _row_id(_blocker(rest_api))

        row = self._row(rest_api, RackArea.FRONT.value, blocker_id)

        assert row['object_id'] is None
        assert row['summary_line'] is None
        assert row['type_id'] is None

    def test_a_mount_row_carries_the_same_keys_as_an_occupant_row(self, rest_api) -> None:
        """One row shape whatever the row is, so the frontend reads one contract"""
        mount_id = _row_id(_mount(rest_api, start_slot=10, height=1))
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))

        mount_row = self._row(rest_api, RackArea.FRONT.value, mount_id)
        blocker_row = self._row(rest_api, RackArea.FRONT.value, blocker_id)

        assert set(mount_row) == set(blocker_row)
        assert mount_row['kind'] == RackMountKind.MOUNT.value
        assert mount_row['color'] is None
        assert blocker_row['type_label'] is None

    def test_the_legend_ignores_the_occupants(self, rest_api) -> None:
        """The legend is types-only, and an occupant has no type"""
        _mount(rest_api, start_slot=10, height=1)
        _blocker(rest_api, start_slot=20, height=2)
        _reservation(rest_api, start_slot=30, height=3)

        legend = self._overview(rest_api)['types_legend']

        assert len(legend) == 1
        assert legend[0]['count'] == 1

    def test_the_total_counts_every_row(self, rest_api) -> None:
        """
        An occupant occupies the rack the same way a mount does

        Which is why the total can exceed the sum of the legend's counts.
        """
        _mount(rest_api, start_slot=10, height=1)
        _blocker(rest_api, start_slot=20, height=2)
        _reservation(rest_api, start_slot=30, height=3)

        assert self._overview(rest_api)['total_mounts'] == 3

    def test_an_unassigned_occupant_is_drawn_in_the_bucket(self, rest_api) -> None:
        """The "still needs re-placing" list, mixed with the unplaced objects"""
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))
        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        row = self._row(rest_api, RackArea.UNASSIGNED.value, blocker_id)

        assert row['kind'] == RackMountKind.BLOCKER.value
        assert row['height'] == 2

    def test_the_occupants_legend_tallies_the_kinds_and_the_slots(self, rest_api) -> None:
        """The tally beside the types legend - what the grid draws as "3 U reserved, 2 U blocked" """
        _mount(rest_api, start_slot=10, height=1)
        _blocker(rest_api, start_slot=20, height=2)
        _reservation(rest_api, start_slot=30, height=3)

        assert self._overview(rest_api)['occupants_legend'] == [
            {'kind': RackMountKind.BLOCKER.value, 'count': 1, 'slots': 2},
            {'kind': RackMountKind.RESERVATION.value, 'count': 1, 'slots': 3},
        ]

    def test_a_rack_without_occupants_has_an_empty_occupants_legend(self, rest_api) -> None:
        """An ordinary rack renders no occupant legend at all rather than two zeroes"""
        _mount(rest_api, start_slot=10, height=1)

        assert self._overview(rest_api)['occupants_legend'] == []

    def test_an_unassigned_occupant_counts_but_holds_no_slot(self, rest_api) -> None:
        """
        The two numbers answer different questions

        It is still one blocker the user has to deal with - which is what makes the unassigned bucket a
        to-do list - but it holds no slot until it is placed again.
        """
        blocker_id = _row_id(_blocker(rest_api, start_slot=20, height=2))
        rest_api.patch(f'{ROUTE_URL}/{RACK_ID}/mounts/{blocker_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        assert self._overview(rest_api)['occupants_legend'] == [
            {'kind': RackMountKind.BLOCKER.value, 'count': 1, 'slots': 0},
        ]

    def test_the_two_legends_account_for_the_total(self, rest_api) -> None:
        """Which is what the occupants legend is for - the types legend alone can not"""
        _mount(rest_api, start_slot=10, height=1)
        _blocker(rest_api, start_slot=20, height=2)
        _reservation(rest_api, start_slot=30, height=3)

        overview = self._overview(rest_api)
        typed = sum(entry['count'] for entry in overview['types_legend'])
        occupants = sum(entry['count'] for entry in overview['occupants_legend'])

        assert typed + occupants == overview['total_mounts'] == 3

    def test_a_height_conflict_row_carries_the_kind_too(self, rest_api) -> None:
        """The shrink pre-check draws the same rows, so it needs the same keys"""
        _blocker(rest_api, start_slot=40, height=2)

        conflicts = rest_api.get(f'{ROUTE_URL}/{RACK_ID}/height_conflicts?height=20').get_json()

        assert conflicts['total'] == 1
        assert conflicts['conflicts'][0]['kind'] == RackMountKind.BLOCKER.value

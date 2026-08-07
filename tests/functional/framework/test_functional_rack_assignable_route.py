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
Functional tests for GET /racks/<rack_id>/assignable_objects/

The picker behind "add an object to this rack", over HTTP against a real MongoDB. Three rules decide the
listing - the type must declare a location field, an object of a RACK-marked type is never mountable, and
an object already in THIS rack is out - and all of them are appended BEHIND the caller's own ?filter=, so
the tests also pin that a filter can not widen the result past them.

An object held by ANOTHER rack stays in the listing, with the hint naming that rack, because mounting it
moves it. ?only_unmounted=true narrows the listing back to the objects in no rack at all.

Every assertion is scoped by a ?filter= on this module's own public_ids rather than by a total count, so
objects seeded by other modules can not make the suite order-dependent
"""
from datetime import datetime, timezone
from http import HTTPStatus
from json import dumps
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/racks'

RACK_TYPE_ID: int = 9581
PLAIN_TYPE_ID: int = 9582
OTHER_PLAIN_TYPE_ID: int = 9583
NO_LOCATION_TYPE_ID: int = 9584

RACK_ID: int = 9591
OBJECT_ID: int = 9592
OTHER_OBJECT_ID: int = 9593
THIRD_OBJECT_ID: int = 9594
OTHER_RACK_ID: int = 9595
NO_LOCATION_OBJECT_ID: int = 9596

RACK_HEIGHT: int = 42
PLAIN_FIELD: str = 'plain-field'
MEMBER_TYPE_LABEL: str = 'Member'
MEMBER_TYPE_ICON: str = 'fa-cube'
MEMBER_TYPE_COLOR: str = '#4b9e46'
OTHER_TYPE_LABEL: str = 'Appliance'
RACK_NAME: str = 'rack-a'
OTHER_RACK_NAME: str = 'rack-b'

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, PLAIN_TYPE_ID, OTHER_PLAIN_TYPE_ID, NO_LOCATION_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    RACK_ID, OTHER_RACK_ID, OBJECT_ID, OTHER_OBJECT_ID, THIRD_OBJECT_ID, NO_LOCATION_OBJECT_ID,
]
MOUNTABLE_IDS: list[int] = [OBJECT_ID, OTHER_OBJECT_ID, THIRD_OBJECT_ID]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'


def _rack_type_doc() -> dict[str, Any]:
    """The Rack CmdbType - objects of it are never assignable"""
    return {
        'public_id': RACK_TYPE_ID,
        'name': 'rack-assignable-type',
        'label': 'Rack',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'special_type': SpecialType.RACK.value,
        'selectable_as_parent': True,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
            # A Rack is placed in the location tree itself, so its type declares a location field too -
            # which is why the RACK exclusion is not made redundant by the location-field rule
            {'type': 'location', 'name': RackField.LOCATION.value, 'label': 'Location'},
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


def _plain_type_doc(public_id: int, name: str, label: str, color: str | None,
                    with_location: bool = True) -> dict[str, Any]:
    """
    An ordinary CmdbType, mountable when it declares a location field

    A rack member is mirrored into the location tree through its own location field, so a type without
    one may not be mounted and is never offered by the picker.
    """
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': PLAIN_FIELD, 'label': 'Plain'}]

    if with_location:
        fields.append({'type': 'location', 'name': RackField.LOCATION.value, 'label': 'Location'})

    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': name,
        'label': label,
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': MEMBER_TYPE_ICON,
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [PLAIN_FIELD]}],
            'summary': {'fields': [PLAIN_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }

    if color is not None:
        doc['ci_explorer_color'] = color

    return doc


def _rack_doc(public_id: int = RACK_ID, name: str = RACK_NAME) -> dict[str, Any]:
    """A Rack CmdbObject - the one the picker is asked about, or another one holding a candidate"""
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


def _member_doc(public_id: int, type_id: int = PLAIN_TYPE_ID, active: bool = True) -> dict[str, Any]:
    """An ordinary CmdbObject that can be mounted"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': active,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': PLAIN_FIELD, 'value': f'member-{public_id}'}],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Rack type and two mountable ordinary types for the module"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    types.insert_many([
        _rack_type_doc(),
        _plain_type_doc(PLAIN_TYPE_ID, 'rack-assignable-member', MEMBER_TYPE_LABEL, MEMBER_TYPE_COLOR),
        _plain_type_doc(OTHER_PLAIN_TYPE_ID, 'rack-assignable-other', OTHER_TYPE_LABEL, None),
        _plain_type_doc(NO_LOCATION_TYPE_ID, 'rack-assignable-nowhere', 'Nowhere', None,
                        with_location=False),
    ])

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


@pytest.fixture(autouse=True)
def _seed_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one rack and three mountable objects, and clears every mount, around each test"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    mounts = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    objects.insert_many([
        _rack_doc(),
        _rack_doc(OTHER_RACK_ID, OTHER_RACK_NAME),
        _member_doc(OBJECT_ID),
        _member_doc(OTHER_OBJECT_ID),
        _member_doc(THIRD_OBJECT_ID, type_id=OTHER_PLAIN_TYPE_ID),
        _member_doc(NO_LOCATION_OBJECT_ID, type_id=NO_LOCATION_TYPE_ID),
    ])
    mounts.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})

    yield

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    mounts.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})


def _own_ids_filter(public_ids: list[int] | None = None) -> str:
    """A ?filter= scoping the listing to this module's own objects, so other seeds can not interfere"""
    return dumps({'public_id': {'$in': public_ids if public_ids is not None else ALL_OBJECT_IDS}})


def _get(rest_api, query: str = '', rack_id: int = RACK_ID):
    """GETs the picker for a rack"""
    return rest_api.get(f'{ROUTE_URL}/{rack_id}/assignable_objects/{query}')


def _ids(response) -> list[int]:
    """The public_ids of a picker response, in the order they were returned"""
    return [row['public_id'] for row in response.get_json()['results']]


def _mount(rest_api, object_id: int, rack_id: int = RACK_ID, **body: Any):
    """POSTs a mount request, so the picker can be asked about an object that is now taken"""
    payload: dict[str, Any] = {'object_id': object_id}
    payload.update(body)

    return rest_api.post(f'{ROUTE_URL}/{rack_id}/mounts/', json=payload)


def _row(response, object_id: int) -> dict[str, Any]:
    """One picker row by object id"""
    return next(row for row in response.get_json()['results'] if row['public_id'] == object_id)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              the three rules                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRules:
    """An object is assignable when its type carries a location field, it is no Rack, and it is not here"""

    def test_a_free_object_is_listed(self, rest_api) -> None:
        """The base case: nothing holds it and it is not a rack"""
        response = _get(rest_api, f'?filter={_own_ids_filter()}')

        assert response.status_code == HTTPStatus.OK
        assert sorted(_ids(response)) == sorted(MOUNTABLE_IDS)

    def test_the_rack_itself_is_never_listed(self, rest_api) -> None:
        """A Rack can not be mounted inside a Rack, itself least of all"""
        assert RACK_ID not in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

    def test_an_object_whose_type_has_no_location_field_is_never_listed(self, rest_api) -> None:
        """
        A member is mirrored into the location tree through its own location field

        Without one there is nowhere to record where the object is, so it can not be a rack member at
        all - the picker must not offer what the mount write would refuse.
        """
        assert NO_LOCATION_OBJECT_ID not in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

    def test_a_member_of_this_rack_drops_out(self, rest_api) -> None:
        """It is already here, so there is nothing to add"""
        _mount(rest_api, OBJECT_ID, area=RackArea.FRONT.value, start_slot=10, height=1)

        assert sorted(_ids(_get(rest_api, f'?filter={_own_ids_filter()}'))) == \
            sorted([OTHER_OBJECT_ID, THIRD_OBJECT_ID])

    def test_an_unplaced_member_of_this_rack_also_drops_out(self, rest_api) -> None:
        """Membership is what makes it 'already here', not placement - an UNASSIGNED member counts"""
        _mount(rest_api, OBJECT_ID)

        assert OBJECT_ID not in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

    def test_an_unmounted_object_comes_back(self, rest_api) -> None:
        """Removing the membership frees the object again"""
        mount_id: int = _mount(rest_api, OBJECT_ID).get_json()['result_id']
        rest_api.delete(f'{ROUTE_URL}/{RACK_ID}/mounts/{mount_id}')

        assert OBJECT_ID in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

    def test_an_object_held_by_another_rack_stays_in_the_listing(self, rest_api) -> None:
        """
        Mounting it here moves it, so hiding it would make the move impossible from the rack view

        This is the one rule that IS rack-specific: the same object is unavailable to the rack holding
        it and available to every other one.
        """
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID)

        assert OBJECT_ID in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

    def test_a_member_of_another_rack_is_offered_placed_or_not(self, rest_api) -> None:
        """A placed member of another rack is as movable as an unplaced one"""
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID,
               area=RackArea.FRONT.value, start_slot=10, height=1)

        assert OBJECT_ID in _ids(_get(rest_api, f'?filter={_own_ids_filter()}'))

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the rows                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRows:
    """A picker row carries what a dropdown renders, and nothing else"""

    def test_a_row_carries_the_summary_line_and_the_type_metadata(self, rest_api) -> None:
        """Resolved server-side, so the frontend needs no request per candidate"""
        rows = _get(rest_api, f'?filter={_own_ids_filter([OBJECT_ID])}').get_json()['results']

        assert len(rows) == 1
        assert rows[0]['public_id'] == OBJECT_ID
        # The same id-prefixed form the mount rows carry (with_type=False), not a bare field value
        assert rows[0]['summary_line'] == f'#{OBJECT_ID} - member-{OBJECT_ID}'
        assert rows[0]['type_id'] == PLAIN_TYPE_ID
        assert rows[0]['type_label'] == MEMBER_TYPE_LABEL
        assert rows[0]['type_icon'] == MEMBER_TYPE_ICON
        assert rows[0]['type_color'] == MEMBER_TYPE_COLOR

    def test_a_row_carries_the_mount_row_keys_plus_the_rack_hint(self, rest_api) -> None:
        """One shape for 'could mount' and 'have mounted', plus where the candidate is now"""
        rows = _get(rest_api, f'?filter={_own_ids_filter([OBJECT_ID])}').get_json()['results']

        assert set(rows[0]) == {
            'public_id', 'summary_line', 'type_id', 'type_label', 'type_icon', 'type_color',
            'assigned_rack_id', 'assigned_rack_name',
        }

    def test_a_free_candidate_names_no_rack(self, rest_api) -> None:
        """Both hint keys are present and null, so the frontend reads one shape rather than two"""
        row = _row(_get(rest_api, f'?filter={_own_ids_filter([OBJECT_ID])}'), OBJECT_ID)

        assert row['assigned_rack_id'] is None
        assert row['assigned_rack_name'] is None

    def test_a_candidate_in_another_rack_names_that_rack_by_id_and_name(self, rest_api) -> None:
        """The hint is what lets the frontend warn that mounting it moves it out of that rack"""
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID)

        row = _row(_get(rest_api, f'?filter={_own_ids_filter([OBJECT_ID])}'), OBJECT_ID)

        assert row['assigned_rack_id'] == OTHER_RACK_ID
        assert row['assigned_rack_name'] == OTHER_RACK_NAME

    def test_a_type_without_a_colour_yields_a_null_colour(self, rest_api) -> None:
        """Nobody picked one under Type Settings - the row still renders"""
        rows = _get(rest_api, f'?filter={_own_ids_filter([THIRD_OBJECT_ID])}').get_json()['results']

        assert rows[0]['type_label'] == OTHER_TYPE_LABEL
        assert rows[0]['type_color'] is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                        pagination, filter and sorting                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectionParameters:
    """The listing speaks the same ?filter= / ?limit= / ?page= / ?sort= / ?order= as every other listing"""

    def test_a_filter_narrows_the_candidates(self, rest_api) -> None:
        """A picker scoped to one type is the common frontend case"""
        query: str = dumps({'type_id': OTHER_PLAIN_TYPE_ID})

        assert _ids(_get(rest_api, f'?filter={query}')) == [THIRD_OBJECT_ID]

    def test_a_filter_cannot_widen_the_result_past_the_rules(self, rest_api) -> None:
        """
        The rules are appended BEHIND the caller's filter, so they can not be overwritten

        A caller asking for exactly the Rack type gets an empty page, not the racks.
        """
        query: str = dumps({'type_id': RACK_TYPE_ID})

        assert _get(rest_api, f'?filter={query}').get_json()['results'] == []

    def test_a_filter_cannot_resurrect_a_member_of_this_rack(self, rest_api) -> None:
        """Asking for a taken object by id still yields nothing"""
        _mount(rest_api, OBJECT_ID)
        query: str = dumps({'public_id': OBJECT_ID})

        assert _get(rest_api, f'?filter={query}').get_json()['results'] == []

    def test_a_filter_cannot_resurrect_a_type_without_a_location_field(self, rest_api) -> None:
        """The positive type marker is as unbypassable as the exclusions"""
        query: str = dumps({'type_id': NO_LOCATION_TYPE_ID})

        assert _get(rest_api, f'?filter={query}').get_json()['results'] == []

    def test_a_pipeline_filter_is_accepted_too(self, rest_api) -> None:
        """The parameter takes an aggregation pipeline as well as a criteria dict"""
        query: str = dumps([{'$match': {'type_id': OTHER_PLAIN_TYPE_ID}}])

        assert _ids(_get(rest_api, f'?filter={query}')) == [THIRD_OBJECT_ID]

    def test_the_page_is_limited_and_the_total_is_not(self, rest_api) -> None:
        """total counts every candidate, count only the page"""
        body = _get(rest_api, f'?filter={_own_ids_filter()}&limit=2&page=1').get_json()

        assert len(body['results']) == 2
        assert body['count'] == 2
        assert body['total'] == len(MOUNTABLE_IDS)

    def test_the_second_page_carries_the_remainder(self, rest_api) -> None:
        """Paging happens in the database, not client-side"""
        query: str = f'?filter={_own_ids_filter()}&limit=2&sort=public_id&order=1'
        first = _ids(_get(rest_api, f'{query}&page=1'))
        second = _ids(_get(rest_api, f'{query}&page=2'))

        assert first == sorted(MOUNTABLE_IDS)[:2]
        assert second == sorted(MOUNTABLE_IDS)[2:]

    def test_the_order_parameter_reverses_the_listing(self, rest_api) -> None:
        """1 is ascending and -1 descending, the Mongo direction encoding used everywhere"""
        query: str = f'?filter={_own_ids_filter()}&sort=public_id'

        assert _ids(_get(rest_api, f'{query}&order=1')) == sorted(MOUNTABLE_IDS)
        assert _ids(_get(rest_api, f'{query}&order=-1')) == sorted(MOUNTABLE_IDS, reverse=True)

    def test_the_active_only_cookie_hides_an_inactive_candidate(self, rest_api,
                                                                database_manager: MongoDatabaseManager,
                                                                database_name: str) -> None:
        """
        The picker honours the same active-objects setting the object list does

        An inactive object is still mountable as far as the two rack rules go, so without the setting it
        stays in the listing - the filter comes from the global preference, not from the rack.
        """
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.update_one({'public_id': OBJECT_ID}, {'$set': {'active': False}})

        query: str = f'?filter={_own_ids_filter()}'

        assert OBJECT_ID in _ids(_get(rest_api, query))
        assert OBJECT_ID not in _ids(_get(rest_api, f'{query}&onlyActiveObjCookie=true'))

    def test_only_unmounted_hides_the_members_of_other_racks(self, rest_api) -> None:
        """
        The toggle behind "hide already-assigned objects"

        An ordinary ?filter= can not express it: the rack a candidate sits in is resolved after the
        query, so filtering on it in the frontend would break the paging.
        """
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID)
        query: str = f'?filter={_own_ids_filter()}'

        assert OBJECT_ID in _ids(_get(rest_api, query))
        assert OBJECT_ID not in _ids(_get(rest_api, f'{query}&only_unmounted=true'))

    def test_only_unmounted_keeps_the_free_objects(self, rest_api) -> None:
        """It narrows the listing, it does not empty it"""
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID)

        listed = _ids(_get(rest_api, f'?filter={_own_ids_filter()}&only_unmounted=true'))

        assert sorted(listed) == sorted([OTHER_OBJECT_ID, THIRD_OBJECT_ID])

    def test_an_unrecognised_flag_value_is_the_default_listing(self, rest_api) -> None:
        """Off unless explicitly asked for - a stale frontend gets the full list, never a 400"""
        _mount(rest_api, OBJECT_ID, rack_id=OTHER_RACK_ID)

        assert OBJECT_ID in _ids(_get(rest_api, f'?filter={_own_ids_filter()}&only_unmounted=nonsense'))

    def test_an_unparsable_filter_is_a_400(self, rest_api) -> None:
        """The parameter parsing refuses garbage before any read happens"""
        response = rest_api.get(
            f'{ROUTE_URL}/{RACK_ID}/assignable_objects/?filter=notjson', unauthorized=True,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  refusals                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRefusals:
    """The rack id in the URL is validated even though it does not narrow the answer"""

    def test_a_missing_rack_is_a_404(self, rest_api) -> None:
        """A typo'd id must not silently list every free object"""
        assert _get(rest_api, rack_id=999999).status_code == HTTPStatus.NOT_FOUND

    def test_a_non_rack_is_a_400(self, rest_api) -> None:
        """An ordinary object has nothing to assign to"""
        assert _get(rest_api, rack_id=OBJECT_ID).status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_member_read_is_a_400(self, rest_api) -> None:
        """Without the exclusion list the listing would be wrong, so it is refused rather than guessed"""
        with patch(
            'cmdb.manager.rack_mounts_manager.RackMountsManager.get_member_object_ids',
            side_effect=RackMountsManagerGetError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_hint_read_is_a_400(self, rest_api) -> None:
        """A row would otherwise claim a candidate is free when it sits in another rack"""
        with patch(
            'cmdb.manager.rack_mounts_manager.RackMountsManager.get_mounts_of_objects',
            side_effect=RackMountsManagerGetError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_location_type_read_is_a_400(self, rest_api) -> None:
        """Without the mountable type ids the listing could offer an unmountable object"""
        with patch(
            'cmdb.manager.types_manager.TypesManager.get_type_ids_with_location_field',
            side_effect=TypesManagerGetError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_candidate_read_is_a_400(self, rest_api) -> None:
        """The aggregation is the listing - a failure there has no partial answer worth returning"""
        with patch(
            'cmdb.manager.objects_manager.ObjectsManager.iterate_query',
            side_effect=ObjectsManagerIterationError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_a_failed_rack_type_read_is_a_400(self, rest_api) -> None:
        """Without the rack type ids the listing could offer a Rack, so it is refused instead"""
        with patch(
            'cmdb.manager.types_manager.TypesManager.get_type_ids_of_special_type',
            side_effect=TypesManagerGetError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_error_is_a_500(self, rest_api) -> None:
        """Anything unforeseen is an internal error, not a misleading empty page"""
        with patch(
            'cmdb.manager.rack_mounts_manager.RackMountsManager.get_member_object_ids',
            side_effect=RuntimeError('boom'),
        ):
            assert _get(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

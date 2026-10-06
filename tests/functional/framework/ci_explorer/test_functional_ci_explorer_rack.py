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
Functional coverage for rack membership in the CI Explorer, through GET /ci_explorer/items

A rack's members hang one hop below the rack's node in the location tree, so the CI Explorer's location graft
shows them without knowing what a rack is - with the graft's inverted buckets (a location's children land in the
parent bucket), only with `with_locations` on, and over bare edges the frontend reads as location edges. Pinned:

  - the rack shows its members, and its own location parent; a member shows its rack
  - the rack's members leave its neighbourhood when they leave the rack
  - a capped neighbourhood keeps the members of the lowest public_id, the same ones on every request
  - nothing of it without `with_locations`, and a types filter applies to the members

The rack, the members and the location tree are written through the real routes, against a database whose
location tree has its root - the shape a production boot gives it
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.location_model.cmdb_location import CmdbLocation

# The rack-location suite's seed: the Rack type, a mountable type with a location field, a datacenter node and
# the candidate objects, plus the helpers that place a rack and mount a member through the routes
from tests.functional.framework.test_functional_rack_locations import (
    MEMBER_WITH_FIELD_ID,
    PARENT_OBJECT_ID,
    RACK_ID,
    RACK_TYPE_ID,
    SECOND_MEMBER_ID,
    CHILD_OBJECT_ID,
    WITH_LOCATION_TYPE_ID,
    _mount,
    _place_rack,
)
# Imported to register them here: the rack suite's licence stub and its two seeding fixtures
from tests.functional.framework.test_functional_rack_locations import (  # noqa: F401 pylint: disable=unused-import
    _ipam_licensed,
    _seed_types,
    fixture_collections,
)
# -------------------------------------------------------------------------------------------------------------------- #

ITEMS_URL: str = '/ci_explorer/items'
RACKS_URL: str = '/racks'
MEMBER_IDS: list[int] = sorted([MEMBER_WITH_FIELD_ID, SECOND_MEMBER_ID, CHILD_OBJECT_ID])

# One slot goes to the rack's location parent, the rest to its members
CAPPED_LIMIT: int = 3
CAPPED_MEMBERS: int = CAPPED_LIMIT - 1


@pytest.fixture(name='rack', autouse=True)
def fixture_rack(rest_api, collections, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """A rack placed under the datacenter with three members; every feature licensed afterwards"""
    assert _place_rack(rest_api).status_code == HTTPStatus.ACCEPTED

    mount_ids: dict[int, int] = {}
    for member_id in MEMBER_IDS:
        response = _mount(rest_api, member_id)
        assert response.status_code == HTTPStatus.CREATED, response.get_json()
        mount_ids[member_id] = response.get_json()['result_id']

    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)
    del collections

    return mount_ids


def _neighbourhood(rest_api, target_id: int, **params: Any) -> dict[str, Any]:
    """The CI Explorer payload around one object"""
    response = rest_api.get(ITEMS_URL, query_string={'target_id': target_id, **params})
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return response.get_json()


def _ids(nodes: list[dict[str, Any]]) -> list[int]:
    """The linked objects' public_ids, sorted"""
    return sorted(node['linked_object']['public_id'] for node in nodes)


class TestTheRack:
    """Selecting the rack"""

    def test_its_members_and_its_location_parent_appear(self, rest_api) -> None:
        """Members in the parent bucket (the graft's inverted semantics), the datacenter in the children"""
        payload = _neighbourhood(rest_api, RACK_ID)

        assert _ids(payload['parent_nodes']) == MEMBER_IDS
        assert _ids(payload['children_nodes']) == [PARENT_OBJECT_ID]

    def test_the_membership_edges_are_location_edges(self, rest_api) -> None:
        """Bare edges - the frontend's marker for a location edge - pointing member -> rack"""
        payload = _neighbourhood(rest_api, RACK_ID)

        assert sorted((edge['from'], edge['to']) for edge in payload['parent_edges']) == [
            (member_id, RACK_ID) for member_id in MEMBER_IDS
        ]
        assert all('metadata' not in edge for edge in payload['parent_edges'])

    def test_a_member_leaving_the_rack_leaves_its_neighbourhood(self, rest_api, rack: dict[str, int]) -> None:
        """The graph follows membership, through the location tree"""
        response = rest_api.delete(f'{RACKS_URL}/{RACK_ID}/mounts/{rack[MEMBER_WITH_FIELD_ID]}')
        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()

        assert MEMBER_WITH_FIELD_ID not in _ids(_neighbourhood(rest_api, RACK_ID)['parent_nodes'])


class TestAMember:
    """Selecting a member"""

    def test_its_rack_appears(self, rest_api) -> None:
        """One hop up the location tree - in the children bucket, inverted"""
        assert _ids(_neighbourhood(rest_api, MEMBER_WITH_FIELD_ID)['children_nodes']) == [RACK_ID]


class TestTheCap:
    """item_limit over a rack's members"""

    def test_the_lowest_member_ids_are_kept(self, rest_api) -> None:
        """Sorted by public_id before the cap - natural order kept arbitrary members"""
        payload = _neighbourhood(rest_api, RACK_ID, item_limit=CAPPED_LIMIT)

        assert _ids(payload['parent_nodes']) == MEMBER_IDS[:CAPPED_MEMBERS]

    def test_the_same_members_on_every_request(self, rest_api, database_manager, database_name) -> None:
        """Rewriting a member's location node does not change which members the cap keeps"""
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        first = _ids(_neighbourhood(rest_api, RACK_ID, item_limit=CAPPED_LIMIT)['parent_nodes'])
        node = locations.find_one_and_delete({'object_id': MEMBER_IDS[0]}, projection={'_id': 0})
        locations.insert_one(node)

        assert _ids(_neighbourhood(rest_api, RACK_ID, item_limit=CAPPED_LIMIT)['parent_nodes']) == first


class TestTheSwitches:
    """with_locations and the types filter"""

    def test_nothing_without_with_locations(self, rest_api) -> None:
        """Membership reaches the graph only through the location graft"""
        payload = _neighbourhood(rest_api, RACK_ID, with_locations='false')

        assert not payload['parent_nodes'] and not payload['children_nodes']

    @pytest.mark.parametrize(('types', 'expected'), [
        ([WITH_LOCATION_TYPE_ID], MEMBER_IDS), ([RACK_TYPE_ID], []),
    ], ids=['member-type', 'rack-type'])
    def test_a_types_filter_applies_to_the_members(self, rest_api, types: list[int], expected: list[int]) -> None:
        """The members are filtered by their own type"""
        payload = _neighbourhood(rest_api, RACK_ID, types_filter=str(types))

        assert _ids(payload['parent_nodes']) == expected

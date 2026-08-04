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
Functional tests for rack membership in the CmdbLocation tree, over the REST routes

The point of the whole design is that **both kinds of member end up in the same place**: one whose type has a
location field and one whose type has none both hang off the rack's node, so how a customer happened to model
a type never decides whether their device appears in the tree. Every test here checks the real
`framework.locations` documents rather than a response body.

Also covered end to end: that the tree follows MEMBERSHIP (unplacing moves nothing), that a rack gaining,
moving and losing a location drags its members with it, that leaving a rack or deleting the rack DELETES the
members' nodes rather than promoting them, and the two drift guards
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.predefined_data.predefined_data_constants import LocationManagedBy
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
# -------------------------------------------------------------------------------------------------------------------- #

RACKS_URL: str = '/racks'
OBJECTS_URL: str = '/objects'
LOCATIONS_URL: str = '/locations'

RACK_TYPE_ID: int = 9651
WITH_LOCATION_TYPE_ID: int = 9652     # a type that HAS a location field
WITHOUT_LOCATION_TYPE_ID: int = 9653  # a type that has NONE - the D1 case

RACK_ID: int = 9661
PARENT_OBJECT_ID: int = 9662          # owns the location the rack is placed under
MEMBER_WITH_FIELD_ID: int = 9671
MEMBER_WITHOUT_FIELD_ID: int = 9672

PARENT_NODE_ID: int = 9681

RACK_HEIGHT: int = 42
LOCATION_FIELD: str = 'dg_location'
NAME_FIELD: str = 'dg-name'
ROOT_NODE_ID: int = 1

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, WITH_LOCATION_TYPE_ID, WITHOUT_LOCATION_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [RACK_ID, PARENT_OBJECT_ID, MEMBER_WITH_FIELD_ID, MEMBER_WITHOUT_FIELD_ID]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'


def _type_doc(public_id: int, name: str, with_location: bool, special_type: str | None = None) -> dict[str, Any]:
    """
    A CmdbType that optionally declares a location field and optionally is the Rack special type

    A Rack names its fields `dg-rack-*`: the write invariants require a non-empty `dg-rack-name`, so a Rack
    type built with the generic `dg-name` would have every write refused.
    """
    name_field: str = RackField.NAME.value if special_type == SpecialType.RACK.value else NAME_FIELD
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': name_field, 'label': 'Name'}]
    section_fields: list[str] = [name_field]

    if special_type == SpecialType.RACK.value:
        fields.append({'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height'})
        section_fields.append(RackField.HEIGHT.value)

    if with_location:
        fields.append({'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'})
        section_fields.append(LOCATION_FIELD)

    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': name,
        'label': name.title(),
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'selectable_as_parent': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{
                'type': 'section',
                'name': RackSection.INFORMATION.value if special_type else 'main',
                'label': 'Information',
                'fields': section_fields,
            }],
            'summary': {'fields': [name_field]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }

    if special_type:
        doc['special_type'] = special_type

    return doc


def _object_doc(public_id: int, type_id: int, name: str, location: Any = None,
                height: int | None = None) -> dict[str, Any]:
    """A CmdbObject; the location field is only added when its type declares one"""
    name_field: str = RackField.NAME.value if type_id == RACK_TYPE_ID else NAME_FIELD
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': name_field, 'value': name}]

    if height is not None:
        fields.append({'type': 'number', 'name': RackField.HEIGHT.value, 'value': height})

    if type_id in (RACK_TYPE_ID, WITH_LOCATION_TYPE_ID):
        fields.append({'type': 'location', 'name': LOCATION_FIELD, 'value': location})

    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': fields,
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Rack type plus one mountable type with a location field and one without"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    types.insert_many([
        _type_doc(RACK_TYPE_ID, 'rack-loc-type', True, SpecialType.RACK.value),
        _type_doc(WITH_LOCATION_TYPE_ID, 'rack-loc-member-with', True),
        _type_doc(WITHOUT_LOCATION_TYPE_ID, 'rack-loc-member-without', False),
    ])

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds a parent location node, a rack (unplaced) and the two candidate members

    The rack starts with NO location so each test can decide when it gains one.
    """
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    mounts = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'public_id': PARENT_NODE_ID})
    mounts.delete_many({'rack_id': RACK_ID})

    objects.insert_many([
        _object_doc(PARENT_OBJECT_ID, WITH_LOCATION_TYPE_ID, 'datacenter', ROOT_NODE_ID),
        _object_doc(RACK_ID, RACK_TYPE_ID, 'rack-a', None, height=RACK_HEIGHT),
        _object_doc(MEMBER_WITH_FIELD_ID, WITH_LOCATION_TYPE_ID, 'server-01', None),
        _object_doc(MEMBER_WITHOUT_FIELD_ID, WITHOUT_LOCATION_TYPE_ID, 'switch-01'),
    ])
    locations.insert_one({
        'public_id': PARENT_NODE_ID,
        'name': 'Datacenter',
        'parent': ROOT_NODE_ID,
        'object_id': PARENT_OBJECT_ID,
        'type_id': WITH_LOCATION_TYPE_ID,
        'type_label': 'Datacenter',
        'type_icon': 'fa-building',
        'type_selectable': True,
    })

    yield objects, locations, mounts

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'object_id': {'$in': ALL_OBJECT_IDS}})
    locations.delete_many({'public_id': PARENT_NODE_ID})
    mounts.delete_many({'rack_id': RACK_ID})


def _rack_payload(location: Any, height: int = RACK_HEIGHT) -> dict[str, Any]:
    """The full Rack payload PUT /objects/<id> expects"""
    return {
        'public_id': RACK_ID,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'value': 'rack-a'},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'value': height},
            {'type': 'location', 'name': LOCATION_FIELD, 'value': location},
        ],
    }


def _place_rack(rest_api, node_id: Any = PARENT_NODE_ID):
    """Gives the rack a location through the ordinary object route"""
    return rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(node_id))


def _mount(rest_api, object_id: int, **body: Any):
    """Mounts an object into the rack"""
    payload: dict[str, Any] = {'object_id': object_id}
    payload.update(body)

    return rest_api.post(f'{RACKS_URL}/{RACK_ID}/mounts/', json=payload)


def _node_of(locations, object_id: int) -> dict[str, Any] | None:
    """Reads an object's stored location node"""
    return locations.find_one({'object_id': object_id})

# -------------------------------------------------------------------------------------------------------------------- #
#                                       both branches land in the same place                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBothBranches:
    """A member with a location field and one without both end up under the rack"""

    def test_a_member_whose_type_has_a_location_field_is_placed(self, rest_api, collections) -> None:
        """The field branch: the field is driven and the ordinary mirror creates the node"""
        _, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        node = _node_of(locations, MEMBER_WITH_FIELD_ID)
        assert node is not None
        assert node['parent'] == rack_node['public_id']

    def test_a_member_whose_type_has_no_location_field_is_placed_too(self, rest_api, collections) -> None:
        """
        The D1 case, and the reason this step exists

        There is no field to mirror, so the node is written directly - but it lands in the same place.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        node = _node_of(locations, MEMBER_WITHOUT_FIELD_ID)
        assert node is not None
        assert node['parent'] == rack_node['public_id']

    def test_both_members_hang_off_the_same_rack_node(self, rest_api, collections) -> None:
        """Indistinguishable in the tree, which is the whole point"""
        _, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        parents = {
            _node_of(locations, MEMBER_WITH_FIELD_ID)['parent'],
            _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent'],
        }
        assert parents == {rack_node['public_id']}

    def test_only_the_field_less_member_is_marked_as_managed(self, rest_api, collections) -> None:
        """
        The marker exists for the node the user cannot correct through a field

        The field-driven node needs no marker: its own object's field says where it belongs.
        """
        _, locations, _ = collections
        _place_rack(rest_api)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        assert _node_of(locations, MEMBER_WITH_FIELD_ID).get('managed_by') is None
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['managed_by'] == LocationManagedBy.RACK.value

    def test_the_field_branch_writes_the_objects_location_field(self, rest_api, collections) -> None:
        """The field is the record for that branch, so it has to actually be set"""
        objects, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        stored = objects.find_one({'public_id': MEMBER_WITH_FIELD_ID})
        field = next(f for f in stored['fields'] if f['name'] == LOCATION_FIELD)
        assert field['value'] == rack_node['public_id']

# -------------------------------------------------------------------------------------------------------------------- #
#                                       the tree follows membership                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTreeFollowsMembership:
    """Placement changes never move anything in the tree - only joining and leaving do"""

    def test_an_unplaced_member_is_still_in_the_tree(self, rest_api, collections) -> None:
        """Assigned without a slot is still assigned"""
        _, locations, _ = collections
        _place_rack(rest_api)

        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is not None

    def test_unplacing_a_member_does_not_move_it(self, rest_api, collections) -> None:
        """
        The tree follows membership, so a placement change is invisible to it

        This is what makes a height shrink non-destructive to the location tree.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        response = _mount(rest_api, MEMBER_WITHOUT_FIELD_ID,
                          area=RackArea.FRONT.value, start_slot=10, height=2)
        mount_id = response.get_json()['result_id']
        before = _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent']

        rest_api.patch(f'{RACKS_URL}/{RACK_ID}/mounts/{mount_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent'] == before

    def test_a_height_shrink_does_not_move_a_member(self, rest_api, collections) -> None:
        """The displaced member keeps its place in the tree - it is still a member"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID, area=RackArea.FRONT.value, start_slot=30, height=2)
        before = _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent']

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(PARENT_NODE_ID, height=10))

        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent'] == before

# -------------------------------------------------------------------------------------------------------------------- #
#                                    the rack's own location drives the members                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRackLocationDrivesMembers:
    """Members follow the rack: they arrive with it, move with it and leave with it"""

    def test_a_member_of_an_unplaced_rack_is_not_in_the_tree(self, rest_api, collections) -> None:
        """There is nowhere to hang it - the documented "then they do not need to be displayed\""""
        _, locations, _ = collections

        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None

    def test_giving_the_rack_a_location_places_its_existing_members(self, rest_api, collections) -> None:
        """
        Mounted first, placed later - the reconcile catches up

        This is why the reconcile reads the rack's current node instead of diffing the change.
        """
        _, locations, _ = collections
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None

        _place_rack(rest_api)

        rack_node = _node_of(locations, RACK_ID)
        assert _node_of(locations, MEMBER_WITH_FIELD_ID)['parent'] == rack_node['public_id']
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent'] == rack_node['public_id']

    def test_moving_the_rack_moves_its_members(self, rest_api, collections) -> None:
        """The members' nodes are re-pointed, not duplicated"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        _place_rack(rest_api, ROOT_NODE_ID)

        rack_node = _node_of(locations, RACK_ID)
        assert rack_node['parent'] == ROOT_NODE_ID
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID)['parent'] == rack_node['public_id']
        assert locations.count_documents({'object_id': MEMBER_WITHOUT_FIELD_ID}) == 1

    def test_the_rack_losing_its_location_removes_its_members(self, rest_api, collections) -> None:
        """
        By decision the members leave the tree rather than being promoted

        Their place in the tree came from the rack.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(None))

        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None

    def test_members_are_not_promoted_to_the_racks_former_parent(self, rest_api, collections) -> None:
        """The explicit opposite of the generic re-parenting behaviour"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(None))

        assert locations.count_documents({'parent': PARENT_NODE_ID, 'object_id': MEMBER_WITHOUT_FIELD_ID}) == 0

# -------------------------------------------------------------------------------------------------------------------- #
#                                          leaving the rack (5a)                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLeavingTheRack:
    """Removing a membership, and deleting either end of one"""

    def test_removing_a_member_removes_its_node(self, rest_api, collections) -> None:
        """Leaving the rack means leaving the tree"""
        _, locations, _ = collections
        _place_rack(rest_api)
        mount_id = _mount(rest_api, MEMBER_WITHOUT_FIELD_ID).get_json()['result_id']

        rest_api.delete(f'{RACKS_URL}/{RACK_ID}/mounts/{mount_id}')

        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None

    def test_removing_a_field_driven_member_clears_its_field(self, rest_api, collections) -> None:
        """A field left pointing at a deleted node would fail the object's next edit"""
        objects, locations, _ = collections
        _place_rack(rest_api)
        mount_id = _mount(rest_api, MEMBER_WITH_FIELD_ID).get_json()['result_id']

        rest_api.delete(f'{RACKS_URL}/{RACK_ID}/mounts/{mount_id}')

        stored = objects.find_one({'public_id': MEMBER_WITH_FIELD_ID})
        field = next(f for f in stored['fields'] if f['name'] == LOCATION_FIELD)
        assert field['value'] is None
        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None

    def test_deleting_a_mounted_object_removes_its_membership(self, rest_api, collections) -> None:
        """5a: the mount row must not outlive the object it points at"""
        _, _, mounts = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.delete(f'{OBJECTS_URL}/{MEMBER_WITHOUT_FIELD_ID}')

        assert mounts.count_documents({'object_id': MEMBER_WITHOUT_FIELD_ID}) == 0

    def test_deleting_the_rack_removes_every_membership(self, rest_api, collections) -> None:
        """5a: no mount row may outlive its rack"""
        _, _, mounts = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert mounts.count_documents({'rack_id': RACK_ID}) == 0

    def test_deleting_the_rack_removes_the_members_from_the_tree(self, rest_api, collections) -> None:
        """The corrected decision: the attached locations are deleted, not promoted"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None
        assert locations.count_documents({'parent': PARENT_NODE_ID}) == 0

    def test_deleting_the_rack_keeps_the_member_objects(self, rest_api, collections) -> None:
        """Deleting a rack deletes the rack, not the devices that were in it"""
        objects, _, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert objects.find_one({'public_id': MEMBER_WITH_FIELD_ID}) is not None
        assert objects.find_one({'public_id': MEMBER_WITHOUT_FIELD_ID}) is not None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the drift guards                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDriftGuards:
    """The tree may not be talked out of agreeing with the rack"""

    def test_a_rack_owned_node_can_not_be_moved_by_hand(self, rest_api, collections) -> None:
        """
        There is no field behind it and nothing in the object form to correct

        So a manual move would leave the tree disagreeing with the rack indefinitely.
        """
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        response = rest_api.patch(f'{LOCATIONS_URL}/{MEMBER_WITHOUT_FIELD_ID}/parent',
                                  json={'parent': ROOT_NODE_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'managed by' in response.get_data(as_text=True)

    def test_a_rack_owned_node_can_not_be_deleted_by_hand(self, rest_api, collections) -> None:
        """Same reasoning as the move"""
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        response = rest_api.delete(f'{LOCATIONS_URL}/{MEMBER_WITHOUT_FIELD_ID}/object')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_field_driven_member_can_not_be_moved_from_the_object_form(self, rest_api, collections) -> None:
        """W9e: the rack owns where its members sit"""
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        payload = _object_doc(MEMBER_WITH_FIELD_ID, WITH_LOCATION_TYPE_ID, 'server-01', ROOT_NODE_ID)
        payload.pop('creation_time')
        response = rest_api.put(f'{OBJECTS_URL}/{MEMBER_WITH_FIELD_ID}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(RACK_ID) in response.get_data(as_text=True)

    def test_an_ordinary_object_can_still_be_moved(self, rest_api, collections) -> None:
        """The guards must not leak onto everything else in the product"""
        response = rest_api.patch(f'{LOCATIONS_URL}/{PARENT_OBJECT_ID}/parent',
                                  json={'parent': ROOT_NODE_ID})

        assert response.status_code != HTTPStatus.BAD_REQUEST


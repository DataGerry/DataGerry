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

A member hangs off its rack's node through its own location field, which is why only a type declaring one may
be mounted at all. Every test here checks the real `framework.locations` documents rather than a response body.

Covered end to end: that mounting places the member under the rack, that a type without a location field is
refused outright, that MOVING a member to another rack re-points its existing node rather than replacing it,
that the tree follows MEMBERSHIP (unplacing moves nothing), that a rack gaining, moving and losing a location
drags its members with it, that leaving a rack or deleting the rack DELETES the members' nodes rather than
promoting them, and the drift guard on the object form
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated Rack View surface is reachable.

    The Rack View is gated behind LicenseFeature.IPAM as an interim decision - a Rack is not an IPAM
    type, see SpecialType.get_license_gated_types - so every /racks route, the RACK type write and
    the Rack object write need the feature unlocked here.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

RACKS_URL: str = '/racks'
OBJECTS_URL: str = '/objects'
LOCATIONS_URL: str = '/locations'

RACK_TYPE_ID: int = 9651
WITH_LOCATION_TYPE_ID: int = 9652     # a type that HAS a location field
WITHOUT_LOCATION_TYPE_ID: int = 9653  # a type that has NONE - the D1 case

RACK_ID: int = 9661
OTHER_RACK_ID: int = 9663             # the rack a member is moved into
PARENT_OBJECT_ID: int = 9662          # owns the location the rack is placed under
MEMBER_WITH_FIELD_ID: int = 9671
SECOND_MEMBER_ID: int = 9673          # a second mountable member
MEMBER_WITHOUT_FIELD_ID: int = 9672   # unmountable: its type declares no location field
CHILD_OBJECT_ID: int = 9674           # hangs under MEMBER_WITH_FIELD_ID in the tree

PARENT_NODE_ID: int = 9681
OTHER_PARENT_NODE_ID: int = 9682

RACK_HEIGHT: int = 42
LOCATION_FIELD: str = 'dg_location'
NAME_FIELD: str = 'dg-name'
ROOT_NODE_ID: int = 1

ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, WITH_LOCATION_TYPE_ID, WITHOUT_LOCATION_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    RACK_ID, OTHER_RACK_ID, PARENT_OBJECT_ID, MEMBER_WITH_FIELD_ID, SECOND_MEMBER_ID,
    MEMBER_WITHOUT_FIELD_ID, CHILD_OBJECT_ID,
]
ALL_NODE_IDS: list[int] = [PARENT_NODE_ID, OTHER_PARENT_NODE_ID]

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

    # Both of these declare a location field; WITHOUT_LOCATION_TYPE_ID is the one that does not
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
    locations.delete_many({'public_id': {'$in': ALL_NODE_IDS}})
    mounts.delete_many({'rack_id': {'$in': [RACK_ID, OTHER_RACK_ID]}})

    objects.insert_many([
        _object_doc(PARENT_OBJECT_ID, WITH_LOCATION_TYPE_ID, 'datacenter', ROOT_NODE_ID),
        _object_doc(RACK_ID, RACK_TYPE_ID, 'rack-a', None, height=RACK_HEIGHT),
        _object_doc(OTHER_RACK_ID, RACK_TYPE_ID, 'rack-b', None, height=RACK_HEIGHT),
        _object_doc(MEMBER_WITH_FIELD_ID, WITH_LOCATION_TYPE_ID, 'server-01', None),
        _object_doc(SECOND_MEMBER_ID, WITH_LOCATION_TYPE_ID, 'server-02', None),
        _object_doc(MEMBER_WITHOUT_FIELD_ID, WITHOUT_LOCATION_TYPE_ID, 'switch-01'),
        _object_doc(CHILD_OBJECT_ID, WITH_LOCATION_TYPE_ID, 'blade-01', None),
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
    locations.delete_many({'public_id': {'$in': ALL_NODE_IDS}})
    mounts.delete_many({'rack_id': {'$in': [RACK_ID, OTHER_RACK_ID]}})


def _rack_payload(location: Any, height: int = RACK_HEIGHT, rack_id: int = RACK_ID,
                  name: str = 'rack-a') -> dict[str, Any]:
    """The full Rack payload PUT /objects/<id> expects"""
    return {
        'public_id': rack_id,
        'type_id': RACK_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'value': name},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'value': height},
            {'type': 'location', 'name': LOCATION_FIELD, 'value': location},
        ],
    }


def _place_rack(rest_api, node_id: Any = PARENT_NODE_ID, rack_id: int = RACK_ID, name: str = 'rack-a'):
    """Gives a rack a location through the ordinary object route"""
    return rest_api.put(f'{OBJECTS_URL}/{rack_id}', json=_rack_payload(node_id, RACK_HEIGHT, rack_id, name))


def _mount(rest_api, object_id: int, rack_id: int = RACK_ID, **body: Any):
    """Mounts an object into a rack"""
    payload: dict[str, Any] = {'object_id': object_id}
    payload.update(body)

    return rest_api.post(f'{RACKS_URL}/{rack_id}/mounts/', json=payload)


def _node_of(locations, object_id: int) -> dict[str, Any] | None:
    """Reads an object's stored location node"""
    return locations.find_one({'object_id': object_id})

# -------------------------------------------------------------------------------------------------------------------- #
#                                        a member lands under its rack                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMemberPlacement:
    """Mounting an object hangs it off the rack's node through its own location field"""

    def test_a_member_whose_type_has_a_location_field_is_placed(self, rest_api, collections) -> None:
        """The field is driven and the ordinary mirror creates the node"""
        _, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        node = _node_of(locations, MEMBER_WITH_FIELD_ID)
        assert node is not None
        assert node['parent'] == rack_node['public_id']

    def test_a_member_whose_type_has_no_location_field_can_not_be_mounted(self, rest_api,
                                                                          collections) -> None:
        """
        There is nowhere to record where the object is, so it can not be a member at all

        The picker never offers such an object either - this is the write path meeting the same rule.
        """
        _, locations, _ = collections
        _place_rack(rest_api)

        response = _mount(rest_api, MEMBER_WITHOUT_FIELD_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _node_of(locations, MEMBER_WITHOUT_FIELD_ID) is None

    def test_every_member_hangs_off_the_same_rack_node(self, rest_api, collections) -> None:
        """One rack, one parent for all of it"""
        _, locations, _ = collections
        _place_rack(rest_api)
        rack_node = _node_of(locations, RACK_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)

        parents = {
            _node_of(locations, MEMBER_WITH_FIELD_ID)['parent'],
            _node_of(locations, SECOND_MEMBER_ID)['parent'],
        }
        assert parents == {rack_node['public_id']}

    def test_mounting_writes_the_objects_location_field(self, rest_api, collections) -> None:
        """The field is the record and the node derives from it, so it has to actually be set"""
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

        _mount(rest_api, SECOND_MEMBER_ID)

        assert _node_of(locations, SECOND_MEMBER_ID) is not None

    def test_unplacing_a_member_does_not_move_it(self, rest_api, collections) -> None:
        """
        The tree follows membership, so a placement change is invisible to it

        This is what makes a height shrink non-destructive to the location tree.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        response = _mount(rest_api, SECOND_MEMBER_ID,
                          area=RackArea.FRONT.value, start_slot=10, height=2)
        mount_id = response.get_json()['result_id']
        before = _node_of(locations, SECOND_MEMBER_ID)['parent']

        rest_api.patch(f'{RACKS_URL}/{RACK_ID}/mounts/{mount_id}',
                       json={'area': RackArea.UNASSIGNED.value})

        assert _node_of(locations, SECOND_MEMBER_ID)['parent'] == before

    def test_a_height_shrink_does_not_move_a_member(self, rest_api, collections) -> None:
        """The displaced member keeps its place in the tree - it is still a member"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, SECOND_MEMBER_ID, area=RackArea.FRONT.value, start_slot=30, height=2)
        before = _node_of(locations, SECOND_MEMBER_ID)['parent']

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(PARENT_NODE_ID, height=10))

        assert _node_of(locations, SECOND_MEMBER_ID)['parent'] == before

# -------------------------------------------------------------------------------------------------------------------- #
#                                    the rack's own location drives the members                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRackLocationDrivesMembers:
    """Members follow the rack: they arrive with it, move with it and leave with it"""

    def test_a_member_of_an_unplaced_rack_is_not_in_the_tree(self, rest_api, collections) -> None:
        """There is nowhere to hang it - the documented "then they do not need to be displayed\""""
        _, locations, _ = collections

        _mount(rest_api, SECOND_MEMBER_ID)

        assert _node_of(locations, SECOND_MEMBER_ID) is None

    def test_giving_the_rack_a_location_places_its_existing_members(self, rest_api, collections) -> None:
        """
        Mounted first, placed later - the reconcile catches up

        This is why the reconcile reads the rack's current node instead of diffing the change.
        """
        _, locations, _ = collections
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)
        assert _node_of(locations, SECOND_MEMBER_ID) is None

        _place_rack(rest_api)

        rack_node = _node_of(locations, RACK_ID)
        assert _node_of(locations, MEMBER_WITH_FIELD_ID)['parent'] == rack_node['public_id']
        assert _node_of(locations, SECOND_MEMBER_ID)['parent'] == rack_node['public_id']

    def test_moving_the_rack_moves_its_members(self, rest_api, collections) -> None:
        """The members' nodes are re-pointed, not duplicated"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, SECOND_MEMBER_ID)

        _place_rack(rest_api, ROOT_NODE_ID)

        rack_node = _node_of(locations, RACK_ID)
        assert rack_node['parent'] == ROOT_NODE_ID
        assert _node_of(locations, SECOND_MEMBER_ID)['parent'] == rack_node['public_id']
        assert locations.count_documents({'object_id': SECOND_MEMBER_ID}) == 1

    def test_the_rack_losing_its_location_removes_its_members(self, rest_api, collections) -> None:
        """
        By decision the members leave the tree rather than being promoted

        Their place in the tree came from the rack.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(None))

        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None
        assert _node_of(locations, SECOND_MEMBER_ID) is None

    def test_members_are_not_promoted_to_the_racks_former_parent(self, rest_api, collections) -> None:
        """The explicit opposite of the generic re-parenting behaviour"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.put(f'{OBJECTS_URL}/{RACK_ID}', json=_rack_payload(None))

        assert locations.count_documents({'parent': PARENT_NODE_ID, 'object_id': SECOND_MEMBER_ID}) == 0

# -------------------------------------------------------------------------------------------------------------------- #
#                                          moving between racks                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMovingBetweenRacks:
    """Mounting an object another rack holds moves it, and its node follows rather than being replaced"""

    def test_the_member_hangs_off_the_new_rack(self, rest_api, collections) -> None:
        """The move is the whole point of offering objects other racks hold"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _place_rack(rest_api, PARENT_NODE_ID, OTHER_RACK_ID, 'rack-b')
        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        other_rack_node = _node_of(locations, OTHER_RACK_ID)
        assert _node_of(locations, MEMBER_WITH_FIELD_ID)['parent'] == other_rack_node['public_id']

    def test_the_node_keeps_its_public_id(self, rest_api, collections) -> None:
        """
        The existing node is re-pointed, not deleted and recreated

        A new id would go stale for anything holding the old one, and the delete would promote the
        member's own children onto the rack it just left.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        _place_rack(rest_api, PARENT_NODE_ID, OTHER_RACK_ID, 'rack-b')
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        before: int = _node_of(locations, MEMBER_WITH_FIELD_ID)['public_id']

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        assert _node_of(locations, MEMBER_WITH_FIELD_ID)['public_id'] == before

    def test_the_member_leaves_exactly_one_node_behind(self, rest_api, collections) -> None:
        """One object, one node - a move must not duplicate it"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _place_rack(rest_api, PARENT_NODE_ID, OTHER_RACK_ID, 'rack-b')
        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        assert locations.count_documents({'object_id': MEMBER_WITH_FIELD_ID}) == 1

    def test_the_objects_location_field_follows_the_move(self, rest_api, collections) -> None:
        """The field is the record, so it has to name the new rack's node"""
        objects, locations, _ = collections
        _place_rack(rest_api)
        _place_rack(rest_api, PARENT_NODE_ID, OTHER_RACK_ID, 'rack-b')
        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        other_rack_node = _node_of(locations, OTHER_RACK_ID)
        stored = objects.find_one({'public_id': MEMBER_WITH_FIELD_ID})
        field = next(f for f in stored['fields'] if f['name'] == LOCATION_FIELD)
        assert field['value'] == other_rack_node['public_id']

    def test_moving_into_a_rack_without_a_location_takes_the_member_out_of_the_tree(
        self, rest_api, collections,
    ) -> None:
        """
        Leaving it where it was would show the object in a rack it no longer belongs to

        The new rack has nowhere to hang it, so the node goes - the same outcome as a rack losing its
        own location.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is not None

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None

    def test_a_child_of_the_moved_member_rides_along(self, rest_api, collections) -> None:
        """
        Nothing under the moved object is promoted onto the rack it left

        This is what the re-point buys over a delete and recreate: delete_location promotes the direct
        children onto the deleted node's own parent, which would strand them in the old rack.
        """
        _, locations, _ = collections
        _place_rack(rest_api)
        _place_rack(rest_api, PARENT_NODE_ID, OTHER_RACK_ID, 'rack-b')
        _mount(rest_api, MEMBER_WITH_FIELD_ID)

        member_node_id: int = _node_of(locations, MEMBER_WITH_FIELD_ID)['public_id']
        child_payload = _object_doc(CHILD_OBJECT_ID, WITH_LOCATION_TYPE_ID, 'blade-01', member_node_id)
        child_payload.pop('creation_time')
        rest_api.put(f'{OBJECTS_URL}/{CHILD_OBJECT_ID}', json=child_payload)

        _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID)

        assert _node_of(locations, CHILD_OBJECT_ID)['parent'] == member_node_id

# -------------------------------------------------------------------------------------------------------------------- #
#                                          leaving the rack (5a)                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLeavingTheRack:
    """Removing a membership, and deleting either end of one"""

    def test_removing_a_member_removes_its_node(self, rest_api, collections) -> None:
        """Leaving the rack means leaving the tree"""
        _, locations, _ = collections
        _place_rack(rest_api)
        mount_id = _mount(rest_api, SECOND_MEMBER_ID).get_json()['result_id']

        rest_api.delete(f'{RACKS_URL}/{RACK_ID}/mounts/{mount_id}')

        assert _node_of(locations, SECOND_MEMBER_ID) is None

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
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.delete(f'{OBJECTS_URL}/{SECOND_MEMBER_ID}')

        assert mounts.count_documents({'object_id': SECOND_MEMBER_ID}) == 0

    def test_deleting_the_rack_removes_every_membership(self, rest_api, collections) -> None:
        """5a: no mount row may outlive its rack"""
        _, _, mounts = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert mounts.count_documents({'rack_id': RACK_ID}) == 0

    def test_deleting_the_rack_removes_the_members_from_the_tree(self, rest_api, collections) -> None:
        """The corrected decision: the attached locations are deleted, not promoted"""
        _, locations, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert _node_of(locations, MEMBER_WITH_FIELD_ID) is None
        assert _node_of(locations, SECOND_MEMBER_ID) is None
        assert locations.count_documents({'parent': PARENT_NODE_ID}) == 0

    def test_deleting_the_rack_keeps_the_member_objects(self, rest_api, collections) -> None:
        """Deleting a rack deletes the rack, not the devices that were in it"""
        objects, _, _ = collections
        _place_rack(rest_api)
        _mount(rest_api, MEMBER_WITH_FIELD_ID)
        _mount(rest_api, SECOND_MEMBER_ID)

        rest_api.delete(f'{OBJECTS_URL}/{RACK_ID}')

        assert objects.find_one({'public_id': MEMBER_WITH_FIELD_ID}) is not None
        assert objects.find_one({'public_id': SECOND_MEMBER_ID}) is not None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the drift guards                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDriftGuards:
    """The tree may not be talked out of agreeing with the rack"""

    def test_a_members_node_can_not_be_re_parented_by_hand(self, rest_api, collections) -> None:
        """
        There is no field behind it and nothing in the object form to correct

        So a manual move would leave the tree disagreeing with the rack indefinitely.
        """
        _place_rack(rest_api)
        _mount(rest_api, SECOND_MEMBER_ID)

        response = rest_api.patch(f'{LOCATIONS_URL}/{SECOND_MEMBER_ID}/parent',
                                  json={'parent': ROOT_NODE_ID})

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


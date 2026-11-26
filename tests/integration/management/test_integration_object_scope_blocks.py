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
Integration tests: the materialised scope blocks computed, stored and kept current in MongoDB (phase 10)

Seeded: a location tree (site > room > rack, a second site), objects placed by their location field or only by their
node, a supernet with a subnet and devices with interface rows. Pinned for ``ObjectScopeBlocks``: the chain from the
field or the node (the root left out), the supernet added, ``stamp``, ``refresh`` writing only what differs,
``refresh_naming`` reaching the objects below a location and in a network, ``ids_with_blocks``. Pinned for the
``ObjectsManager`` hooks: an insert stores its block, an update recomputes it (a sent one is never kept) and a subnet's
new supernet reaches its devices, a location field set by the bulk write, a deleted network scrubbed from its devices,
a Type statement shrinking a block. Pinned for the related list (phase 11): both directions with their relation, a
deleted relation leaving both ends, a deleted object leaving the ends naming it
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks, relation_endpoints
from cmdb.manager.objects_propagation_helper import RawUpdate
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model.cmdb_object_relation import CmdbObjectRelation
from cmdb.models.type_model import CmdbType

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

SITE, ROOM, RACK, OTHER_SITE = 97001, 97002, 97003, 97004
PLACED, NODE_ONLY, UNPLACED = 97011, 97012, 97013
SUPERNET, SUBNET, OTHER_SUPERNET, DEVICE = 97021, 97022, 97023, 97024
INSERTED: int = 97031
OBJECT_IDS: list[int] = [SITE, ROOM, RACK, OTHER_SITE, PLACED, NODE_ONLY, UNPLACED, SUPERNET, SUBNET, OTHER_SUPERNET,
                         DEVICE, INSERTED]
SITE_NODE, ROOM_NODE, RACK_NODE, OTHER_NODE, NODE_ONLY_NODE = 97101, 97102, 97103, 97104, 97105
NODE_IDS: list[int] = [SITE_NODE, ROOM_NODE, RACK_NODE, OTHER_NODE, NODE_ONLY_NODE]
ROOT_NODE: int = 1
TYPE_ID: int = 97201
DEVICE_ADDRESS: str = '10.1.0.5'
ENCODED_ADDRESS: str = '4:0a010005'
EMPTY_BLOCK: dict[str, list[Any]] = {'locations': [], 'networks': [], 'ips': [], 'related': []}


def _location(node_id: int | None) -> dict[str, Any]:
    """A location field entry"""
    return {'name': 'loc', 'type': 'location', 'value': node_id}


def _object(public_id: int, fields: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """A stored object"""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'author_id': 1, 'active': True, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': fields or [], 'multi_data_sections': [], **extra}


def _interfaces(subnet_id: int, address: str = DEVICE_ADDRESS) -> list[dict[str, Any]]:
    """One interface row"""
    return [{'section_id': 'dg-ipam-interface', 'highest_id': 1, 'values': [{'multi_data_id': 1, 'data': [
        {'name': 'dg-interface-subnet', 'value': subnet_id, 'type': 'ref'},
        {'name': 'dg-interface-ip-address', 'value': address, 'type': 'text'}]}]}]


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The tree, the network, the objects - no block stored yet; all removed after"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_one({
        'public_id': TYPE_ID, 'name': 'scope-blocks', 'label': 'T', 'author_id': 1, 'active': True, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'location', 'name': 'loc', 'label': 'Location'}],
        'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': []},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['loc']}]},
        'acl': {'activated': False, 'groups': {'includes': {}}}})
    database[CmdbObject.COLLECTION].insert_many([
        _object(SITE, [_location(ROOT_NODE)]), _object(ROOM, [_location(SITE_NODE)]),
        _object(RACK, [_location(ROOM_NODE)]), _object(OTHER_SITE, [_location(ROOT_NODE)]),
        _object(PLACED, [_location(RACK_NODE)]), _object(NODE_ONLY), _object(UNPLACED, [_location(None)]),
        _object(SUPERNET), _object(OTHER_SUPERNET),
        _object(SUBNET, [{'name': 'dg-supernet-ref', 'type': 'ref', 'value': SUPERNET}]),
        _object(DEVICE, multi_data_sections=_interfaces(SUBNET)),
    ])
    nodes = {SITE_NODE: (SITE, ROOT_NODE), ROOM_NODE: (ROOM, SITE_NODE), RACK_NODE: (RACK, ROOM_NODE),
             OTHER_NODE: (OTHER_SITE, ROOT_NODE), NODE_ONLY_NODE: (NODE_ONLY, ROOM_NODE)}
    database[CmdbLocation.COLLECTION].insert_many([
        {'public_id': node_id, 'name': str(object_id), 'parent': parent, 'object_id': object_id, 'type_id': TYPE_ID}
        for node_id, (object_id, parent) in nodes.items()])

    yield database[CmdbObject.COLLECTION]

    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': OBJECT_IDS}})
    database[CmdbLocation.COLLECTION].delete_many({'public_id': {'$in': NODE_IDS}})
    database[CmdbType.COLLECTION].delete_one({'public_id': TYPE_ID})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> ObjectsManager:
    """The objects' manager of the test database"""
    return ObjectsManager(database_manager, database_name)


def _block(objects: Any, public_id: int) -> Any:
    """The stored block, None when none is stored"""
    return objects.find_one({'public_id': public_id}).get('_scope')


class TestComputed:
    """blocks_of / block_of"""

    @pytest.mark.parametrize('public_id, locations', [
        (SITE, []),
        (ROOM, [SITE]),
        (PLACED, [SITE, ROOM, RACK]),
        (NODE_ONLY, [SITE, ROOM]),
        (UNPLACED, []),
        (DEVICE, []),
    ], ids=['top-level', 'one-down', 'three-down', 'node-only', 'unplaced', 'no-location'])
    def test_the_chain(self, objects: Any, manager: ObjectsManager, public_id: int, locations: list[int]) -> None:
        """From the location field, else the node; the root left out"""
        document = objects.find_one({'public_id': public_id}, {'_id': 0})

        assert ObjectScopeBlocks(manager).block_of(document)['locations'] == locations

    def test_a_device_names_its_subnet_its_supernet_and_its_address(self, objects: Any,
                                                                      manager: ObjectsManager) -> None:
        """One subnet read"""
        document = objects.find_one({'public_id': DEVICE}, {'_id': 0})

        assert ObjectScopeBlocks(manager).block_of(document) == {
            'locations': [], 'networks': [SUPERNET, SUBNET], 'ips': [ENCODED_ADDRESS], 'related': []}

    def test_a_state_about_to_be_written_is_judged_by_its_own_placement(self, objects: Any,
                                                                          manager: ObjectsManager) -> None:
        """A new location value counts, not the stored node"""
        moved = {**objects.find_one({'public_id': PLACED}, {'_id': 0}), 'fields': [_location(OTHER_NODE)]}

        assert ObjectScopeBlocks(manager).block_of(moved)['locations'] == [OTHER_SITE]

    @pytest.mark.usefixtures('objects')
    def test_stamp_replaces_a_brought_block(self, manager: ObjectsManager) -> None:
        """Whatever a document carried"""
        document = {'public_id': INSERTED, 'fields': [_location(ROOM_NODE)], '_scope': {'locations': [1]}}

        ObjectScopeBlocks(manager).stamp([document])

        assert document['_scope'] == {'locations': [SITE, ROOM], 'networks': [], 'ips': [], 'related': []}


class TestStored:
    """refresh / refresh_naming / ids_with_blocks"""

    def test_refresh_writes_only_what_differs(self, objects: Any, manager: ObjectsManager) -> None:
        """A second refresh writes nothing; a gone id is passed over"""
        blocks = ObjectScopeBlocks(manager)

        assert blocks.refresh([PLACED, DEVICE, 1]) == 2
        assert blocks.refresh([PLACED, DEVICE]) == 0
        assert _block(objects, PLACED)['locations'] == [SITE, ROOM, RACK]

    def test_an_empty_block_is_stored_too(self, objects: Any, manager: ObjectsManager) -> None:
        """Never missing after a refresh"""
        ObjectScopeBlocks(manager).refresh([SITE])

        assert _block(objects, SITE) == EMPTY_BLOCK

    def test_a_moved_location_reaches_every_object_below_it(self, objects: Any, manager: ObjectsManager) -> None:
        """The room moved to the other site: the room, the rack, the placed object and the node-only one follow"""
        ObjectScopeBlocks(manager).refresh(OBJECT_IDS)
        objects.database[CmdbLocation.COLLECTION].update_one({'public_id': ROOM_NODE},
                                                              {'$set': {'parent': OTHER_NODE}})
        objects.update_one({'public_id': ROOM}, {'$set': {'fields': [_location(OTHER_NODE)]}})

        ObjectScopeBlocks(manager).refresh_naming([ROOM])

        assert [_block(objects, public_id)['locations'] for public_id in (ROOM, RACK, PLACED, NODE_ONLY)] == [
            [OTHER_SITE], [ROOM, OTHER_SITE], [ROOM, RACK, OTHER_SITE], [ROOM, OTHER_SITE]]
        assert _block(objects, SITE) == EMPTY_BLOCK

    def test_nothing_named_refreshes_nothing(self, manager: ObjectsManager) -> None:
        """No read, nothing written"""
        assert ObjectScopeBlocks(manager).refresh_naming([]) == 0

    def test_the_best_effort_refresh_answers_false_instead_of_raising(
            self, manager: ObjectsManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """For a request already failing with an error of its own"""
        def _failing(*_args: Any, **_kwargs: Any) -> None:
            raise BaseManagerGetError('down')

        monkeypatch.setattr(manager, 'get_distinct', _failing)

        assert ObjectScopeBlocks(manager).try_refresh_naming([PLACED]) is False

    @pytest.mark.usefixtures('objects')
    def test_the_best_effort_refresh_answers_true(self, manager: ObjectsManager) -> None:
        """Refreshed"""
        assert ObjectScopeBlocks(manager).try_refresh_naming([PLACED]) is True

    def test_ids_with_blocks(self, objects: Any, manager: ObjectsManager) -> None:
        """Matching a filter and holding a list that is not empty"""
        blocks = ObjectScopeBlocks(manager)
        blocks.refresh(OBJECT_IDS)

        assert sorted(blocks.ids_with_blocks([{'public_id': {'$in': [SITE, ROOM, DEVICE]}}])) == [ROOM, DEVICE]
        assert not blocks.ids_with_blocks([])


class TestRelated:
    """The related list read from the object relations (phase 11, 9.7)"""

    RELATION_IDS: list[int] = [97301, 97302]

    @pytest.fixture(name='relations')
    def fixture_relations(self, objects: Any) -> Iterator[Any]:
        """Device - placed (relation 5), site - device (relation 6); removed after"""
        collection = objects.database[CmdbObjectRelation.COLLECTION]
        collection.insert_many([
            {'public_id': 97301, 'relation_id': 5, 'relation_parent_id': DEVICE, 'relation_child_id': PLACED},
            {'public_id': 97302, 'relation_id': 6, 'relation_parent_id': SITE, 'relation_child_id': DEVICE}])

        yield collection

        collection.delete_many({'public_id': {'$in': self.RELATION_IDS}})

    def test_both_directions_with_their_relation(self, objects: Any, relations: Any,
                                                 manager: ObjectsManager) -> None:
        """The device is parent of one, child of the other"""
        document = objects.find_one({'public_id': DEVICE}, {'_id': 0})

        assert relations.count_documents({}) >= 2
        assert ObjectScopeBlocks(manager).block_of(document)['related'] == [{'object': SITE, 'relation': 6},
                                                                            {'object': PLACED, 'relation': 5}]

    def test_refresh_endpoints_reaches_both_ends(self, objects: Any, relations: Any,
                                                 manager: ObjectsManager) -> None:
        """After a relation is deleted, both ends lose it"""
        blocks = ObjectScopeBlocks(manager)
        blocks.refresh([DEVICE, PLACED])
        deleted = relations.find_one_and_delete({'public_id': 97301}, {'_id': 0})

        assert ObjectScopeBlocks(manager).refresh_endpoints([deleted]) == 2
        assert _block(objects, PLACED)['related'] == []
        assert _block(objects, DEVICE)['related'] == [{'object': SITE, 'relation': 6}]

    def test_a_deleted_object_leaves_its_related_ends(self, objects: Any, relations: Any,
                                                      manager: ObjectsManager) -> None:
        """refresh_naming reaches the objects whose related list names it"""
        ObjectScopeBlocks(manager).refresh([DEVICE, PLACED, SITE])
        relations.delete_many({'relation_child_id': PLACED})
        objects.delete_one({'public_id': PLACED})

        ObjectScopeBlocks(manager).refresh_naming([PLACED])

        assert _block(objects, DEVICE)['related'] == [{'object': SITE, 'relation': 6}]

    def test_the_best_effort_endpoint_refresh_answers_false_instead_of_raising(
            self, manager: ObjectsManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Beside a write that may have failed part-way"""
        def _failing(*_args: Any, **_kwargs: Any) -> None:
            raise BaseManagerIterationError('down')

        monkeypatch.setattr(manager, 'aggregate_all', _failing)

        assert ObjectScopeBlocks(manager).try_refresh_endpoints(
            [{'relation_parent_id': DEVICE, 'relation_child_id': PLACED}]) is False
        assert ObjectScopeBlocks(manager).try_refresh_endpoints([]) is True


def test_relation_endpoints() -> None:
    """Both ends, once, junk left out"""
    assert relation_endpoints([{'relation_parent_id': 3, 'relation_child_id': 1},
                               {'relation_parent_id': 1, 'relation_child_id': True}, {}]) == [1, 3]


class TestTheManagerHooks:
    """Every ObjectsManager write keeps the block current"""

    def test_an_insert_stores_its_block(self, objects: Any, manager: ObjectsManager) -> None:
        """Computed before the write - a sent one is replaced"""
        manager.insert_object({**_object(INSERTED, [_location(RACK_NODE)]), '_scope': {'locations': [OTHER_SITE]}})

        assert _block(objects, INSERTED) == {'locations': [SITE, ROOM, RACK], 'networks': [], 'ips': [], 'related': []}

    def test_an_update_recomputes_the_block(self, objects: Any, manager: ObjectsManager) -> None:
        """The new placement; a block sent along is dropped"""
        stored = objects.find_one({'public_id': PLACED}, {'_id': 0})

        manager.update_object(PLACED, {**stored, 'fields': [_location(OTHER_NODE)], '_scope': {'locations': [SITE]}})

        assert _block(objects, PLACED)['locations'] == [OTHER_SITE]

    def test_a_compare_and_swap_that_missed_writes_no_block(self, objects: Any, manager: ObjectsManager) -> None:
        """Nothing written, nothing recomputed"""
        stored = objects.find_one({'public_id': PLACED}, {'_id': 0})

        assert manager.update_object(PLACED, stored, expected={'version': 'another'}) is False
        assert _block(objects, PLACED) is None

    def test_a_subnets_new_supernet_reaches_its_devices(self, objects: Any, manager: ObjectsManager) -> None:
        """Through the update of the subnet"""
        ObjectScopeBlocks(manager).refresh([DEVICE])
        stored = objects.find_one({'public_id': SUBNET}, {'_id': 0})

        manager.update_object(SUBNET, {**stored, 'fields': [{'name': 'dg-supernet-ref', 'type': 'ref',
                                                             'value': OTHER_SUPERNET}]})

        assert _block(objects, DEVICE)['networks'] == [SUBNET, OTHER_SUPERNET]  # ascending: 97022 < 97023

    def test_a_partial_update_recomputes_too(self, objects: Any, manager: ObjectsManager) -> None:
        """Only the interface rows sent"""
        manager.update_object(DEVICE, {'multi_data_sections': _interfaces(SUBNET, '10.1.0.6')}, partial=True)

        assert _block(objects, DEVICE)['ips'] == ['4:0a010006']

    def test_the_bulk_location_write(self, objects: Any, manager: ObjectsManager) -> None:
        """set_location_field_for_objects"""
        manager.set_location_field_for_objects([PLACED], OTHER_NODE)

        assert _block(objects, PLACED)['locations'] == [OTHER_SITE]

    def test_a_deleted_network_leaves_its_devices(self, objects: Any, manager: ObjectsManager) -> None:
        """The reference scrub refreshes every object naming the deleted id"""
        ObjectScopeBlocks(manager).refresh([DEVICE])
        objects.delete_one({'public_id': SUBNET})

        manager.delete_all_object_references([SUBNET])

        assert _block(objects, DEVICE) == {'locations': [], 'networks': [], 'ips': [ENCODED_ADDRESS], 'related': []}

    def test_a_type_statement_shrinks_a_block(self, objects: Any, manager: ObjectsManager) -> None:
        """The interface section removed from the Type's objects"""
        ObjectScopeBlocks(manager).refresh([DEVICE])

        manager.apply_raw_updates([RawUpdate(filter_query={'type_id': TYPE_ID, 'public_id': DEVICE},
                                             update={'$set': {'multi_data_sections': []}})])

        assert _block(objects, DEVICE) == EMPTY_BLOCK

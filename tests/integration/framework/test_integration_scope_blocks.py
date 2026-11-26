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
Integration tests: the scope building blocks matched against real data in MongoDB (phase 9 steps 4-6, phase 10)

Seeded: a location tree (site > room > rack > mounted device, and a device elsewhere), a supernet with two subnets and
devices with interface rows in them, a person linked to a user and a person group linked to a user group, objects
whose person selectors name them. The scope blocks are computed by the real ``ObjectScopeBlocks.refresh``, the tokens
resolved by the real ``ScopeResolver``, the compiler builds the filter, and the objects collection answers. Pinned:
``within`` reaches the location itself, its room, rack and the mounted device, not the device elsewhere - an
unplaced location only itself; ``in_network`` by subnet, by supernet and by CIDR (the addresses inside it); the user
tokens; an unlinked user matches nothing
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler import (
    MULTIPLE_PERSON_KIND,
    ScopeField,
    ScopeResolver,
    compile_scope,
    scope_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 25, tzinfo=timezone.utc)
SITE, ROOM, RACK, MOUNTED, ELSEWHERE = 9801, 9802, 9803, 9804, 9805
SUPERNET, SUBNET_A, SUBNET_B = 9810, 9811, 9812
DEVICE_A, DEVICE_B, DEVICE_NONE = 9821, 9822, 9823
PERSON, GROUP, OWNED, GROUP_OWNED, UNOWNED = 9831, 9832, 9833, 9834, 9835
OBJECT_IDS: list[int] = [SITE, ROOM, RACK, MOUNTED, ELSEWHERE, SUPERNET, SUBNET_A, SUBNET_B, DEVICE_A, DEVICE_B,
                         DEVICE_NONE, PERSON, GROUP, OWNED, GROUP_OWNED, UNOWNED]
NODE_IDS: list[int] = [9841, 9842, 9843, 9844, 9845]
SUBNET_TYPE_ID, SUPERNET_TYPE_ID, PLAIN_TYPE_ID = 9851, 9852, 9853
USER: CmdbUser = CmdbUser(public_id=9861, user_name='scope-blocks', active=True, group_ids=[9862])
STRANGER: CmdbUser = CmdbUser(public_id=9863, user_name='scope-stranger', active=True, group_ids=[9864])
FIELDS: dict[str, ScopeField] = {'owner': ScopeField('person', selectable=frozenset({'PERSON'})),
                                 'team': ScopeField(MULTIPLE_PERSON_KIND, selectable=frozenset({'PERSON_GROUP'}))}


def _object(public_id: int, type_id: int = PLAIN_TYPE_ID, fields: list[dict[str, Any]] | None = None,
            **extra: Any) -> dict[str, Any]:
    """A stored object"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'fields': fields or [], **extra}


def _interface(subnet_id: int, address: str) -> list[dict[str, Any]]:
    """The interface rows of a device in a subnet"""
    return [{'section_id': 'dg-ipam-interface', 'values': [{'multi_data_id': 0, 'data': [
        {'name': 'dg-interface-ip-address', 'value': address},
        {'name': 'dg-interface-subnet', 'value': subnet_id}]}]}]


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The tree, the networks, the persons"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbType.COLLECTION].count_documents({'special_type': {'$in': ['SUBNET', 'SUPERNET']}}) == 0
    database[CmdbType.COLLECTION].insert_many([
        {'public_id': SUBNET_TYPE_ID, 'name': 'scope-subnet', 'label': 'S', 'special_type': 'SUBNET', 'fields': []},
        {'public_id': SUPERNET_TYPE_ID, 'name': 'scope-supernet', 'label': 'N', 'special_type': 'SUPERNET',
         'fields': []}])
    database[CmdbObject.COLLECTION].insert_many([
        *[_object(object_id) for object_id in (SITE, ROOM, RACK, MOUNTED, ELSEWHERE)],
        _object(SUPERNET, SUPERNET_TYPE_ID, [{'name': 'dg-network-range', 'value': '10.0.0.0/8'}]),
        _object(SUBNET_A, SUBNET_TYPE_ID, [{'name': 'dg-network-range', 'value': '10.1.0.0/16'},
                                           {'name': 'dg-supernet-ref', 'value': SUPERNET}]),
        _object(SUBNET_B, SUBNET_TYPE_ID, [{'name': 'dg-network-range', 'value': '192.168.0.0/24'}]),
        _object(DEVICE_A, multi_data_sections=_interface(SUBNET_A, '10.1.0.5')),
        _object(DEVICE_B, multi_data_sections=_interface(SUBNET_B, '192.168.0.7')),
        _object(DEVICE_NONE),
        _object(PERSON, system_ref={'kind': 'user', 'id': USER.public_id}),
        _object(GROUP, system_ref={'kind': 'user_group', 'id': 9862}),
        _object(OWNED, fields=[{'name': 'owner', 'value': PERSON}]),
        _object(GROUP_OWNED, fields=[{'name': 'team', 'value': [GROUP, 1]}]),
        _object(UNOWNED, fields=[{'name': 'owner', 'value': 1}]),
    ])
    parents: dict[int, int] = {SITE: 1, ROOM: 9841, RACK: 9842, MOUNTED: 9843, ELSEWHERE: 1}
    database[CmdbLocation.COLLECTION].insert_many([
        {'public_id': node_id, 'name': str(object_id), 'parent': parents[object_id], 'object_id': object_id,
         'type_id': PLAIN_TYPE_ID} for node_id, object_id in zip(NODE_IDS, (SITE, ROOM, RACK, MOUNTED, ELSEWHERE))])
    ObjectScopeBlocks(ObjectsManager(database_manager, database_name)).refresh(OBJECT_IDS)

    yield

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SUBNET_TYPE_ID, SUPERNET_TYPE_ID]}})
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': OBJECT_IDS}})
    database[CmdbLocation.COLLECTION].delete_many({'public_id': {'$in': NODE_IDS}})


def _matched(database_manager: MongoDatabaseManager, database_name: str, user: CmdbUser,
             *blocks: dict[str, Any]) -> list[int]:
    """The seeded objects the scope matches for the user"""
    resolver = ScopeResolver(ObjectsManager(database_manager, database_name))
    context = resolver.resolve(user, scope_references([list(blocks)]))
    criteria = {'$and': [compile_scope(list(blocks), FIELDS, NOW, context), {'public_id': {'$in': OBJECT_IDS}}]}

    return sorted(document['public_id'] for document in
                  database_manager.connector.client[database_name][CmdbObject.COLLECTION].find(criteria))


@pytest.mark.parametrize('user, block, expected', [
    (USER, {'within': SITE}, [SITE, ROOM, RACK, MOUNTED]),
    (USER, {'within': RACK}, [RACK, MOUNTED]),
    (USER, {'within': DEVICE_NONE}, [DEVICE_NONE]),
    (USER, {'in_network': SUBNET_A}, [DEVICE_A]),
    (USER, {'in_network': SUPERNET}, [DEVICE_A]),
    (USER, {'in_network': '192.168.0.0/16'}, [DEVICE_B]),
    (USER, {'in_network': '10.0.0.0/8'}, [DEVICE_A]),
    (USER, {'in_network': '172.16.0.0/12'}, []),
    (USER, {'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}}, [OWNED]),
    (USER, {'field': 'team', 'op': 'contains', 'value': {'user': 'groups'}}, [GROUP_OWNED]),
    (STRANGER, {'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}}, []),
], ids=['within-site', 'within-rack', 'unplaced-location', 'subnet', 'supernet', 'cidr', 'cidr-supernet', 'cidr-empty',
        'my-person', 'my-groups', 'unlinked-user'])
def test_each_block(database_manager: MongoDatabaseManager, database_name: str, user: CmdbUser,
                    block: dict[str, Any], expected: list[int]) -> None:
    """Resolved per user, matched by MongoDB"""
    assert _matched(database_manager, database_name, user, block) == expected


def test_blocks_combine(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """All must hold"""
    assert _matched(database_manager, database_name, USER, {'within': SITE}, {'within': RACK}) == [RACK, MOUNTED]

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
Integration tests for cmdb.database.updater.versions.updater_20261128 against a real MongoDB

Every stored object gets its scope block - the location chain, the networks and addresses of its interface rows; a
second run writes nothing; a run that stopped part-way is finished; a database without objects gets only the stamp
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261128 import Update20261128
from cmdb.manager import ObjectsManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261128'
OBJECTS: str = 'framework.objects'
LOCATIONS: str = 'framework.locations'
VERSION: int = 20261128
SITE, PLACED, SUBNET, DEVICE = 11, 12, 13, 14
SITE_NODE, ROOT_NODE = 21, 1
EXPECTED: dict[int, dict[str, list[Any]]] = {
    SITE: {'locations': [], 'networks': [], 'ips': [], 'related': []},
    PLACED: {'locations': [SITE], 'networks': [], 'ips': [], 'related': []},
    SUBNET: {'locations': [], 'networks': [], 'ips': [], 'related': []},
    DEVICE: {'locations': [], 'networks': [SUBNET], 'ips': ['4:0a000001'], 'related': []},
}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, Any]]:
    """An empty database, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)

    yield name, client[name]

    client.drop_database(name)


def _seed(database: Any) -> None:
    """A site, an object placed in it, a subnet and a device with an interface in it"""
    database[LOCATIONS].insert_many([
        {'public_id': ROOT_NODE, 'name': 'Root', 'parent': 0, 'object_id': 0},
        {'public_id': SITE_NODE, 'name': 'site', 'parent': ROOT_NODE, 'object_id': SITE}])
    database[OBJECTS].insert_many([
        {'public_id': SITE, 'type_id': 1, 'fields': [{'name': 'loc', 'type': 'location', 'value': ROOT_NODE}]},
        {'public_id': PLACED, 'type_id': 1, 'fields': [{'name': 'loc', 'type': 'location', 'value': SITE_NODE}]},
        {'public_id': SUBNET, 'type_id': 2, 'fields': []},
        {'public_id': DEVICE, 'type_id': 1, 'fields': [], 'multi_data_sections': [
            {'section_id': 'dg-ipam-interface', 'values': [{'multi_data_id': 1, 'data': [
                {'name': 'dg-interface-subnet', 'value': SUBNET}, {'name': 'dg-interface-ip-address',
                                                                   'value': '10.0.0.1'}]}]}]},
    ])


def _run(database_manager: MongoDatabaseManager, name: str) -> None:
    """One run"""
    Update20261128(database_manager, name).start_update()


def _blocks(database: Any) -> dict[int, Any]:
    """Every object's stored block"""
    return {document['public_id']: document.get('_scope') for document in database[OBJECTS].find({}, {'_id': 0})}


def _version(database: Any) -> Any:
    """The stamped updater version"""
    return database['settings.conf'].find_one({'_id': 'updater'})['version']


def test_every_object_gets_its_block(database_manager: MongoDatabaseManager, scratch: tuple[str, Any]) -> None:
    """Computed by the live code; the version stamped"""
    name, database = scratch
    _seed(database)

    _run(database_manager, name)

    assert _blocks(database) == EXPECTED
    assert _version(database) == VERSION


def test_a_second_run_writes_nothing(database_manager: MongoDatabaseManager, scratch: tuple[str, Any]) -> None:
    """Every block equal to the computed one - no refresh writes a block"""
    name, database = scratch
    _seed(database)
    _run(database_manager, name)

    assert ObjectScopeBlocks(ObjectsManager(database_manager, name)).refresh(list(EXPECTED)) == 0
    _run(database_manager, name)

    assert _blocks(database) == EXPECTED


def test_a_run_stopped_part_way_is_finished(database_manager: MongoDatabaseManager, scratch: tuple[str, Any]) -> None:
    """Some blocks written, one stale: the next run completes and corrects them"""
    name, database = scratch
    _seed(database)
    database[OBJECTS].update_one({'public_id': PLACED}, {'$set': {'_scope': EXPECTED[PLACED]}})
    database[OBJECTS].update_one({'public_id': DEVICE}, {'$set': {'_scope': {'locations': [SITE]}}})

    _run(database_manager, name)

    assert _blocks(database) == EXPECTED


def test_no_object_writes_only_the_stamp(database_manager: MongoDatabaseManager, scratch: tuple[str, Any]) -> None:
    """A fresh database"""
    name, database = scratch

    _run(database_manager, name)

    assert database[OBJECTS].count_documents({}) == 0
    assert _version(database) == VERSION

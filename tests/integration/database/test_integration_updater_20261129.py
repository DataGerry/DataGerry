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
Integration tests for cmdb.database.updater.versions.updater_20261129 against a real MongoDB

A block stored before phase 11 gains its related list - the other end of each object relation, with its relation; a
second run writes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261129 import Update20261129
from cmdb.manager import ObjectsManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261129'
OBJECTS: str = 'framework.objects'
RELATIONS: str = 'framework.objectRelations'
SERVICE, SERVER = 11, 12
RELATION_ID: int = 7
OLD_BLOCK: dict[str, list[Any]] = {'locations': [], 'networks': [], 'ips': []}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, Any]]:
    """A database with a block from before phase 11 and one relation, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    client[name][OBJECTS].insert_many([{'public_id': public_id, 'type_id': 1, 'fields': [], '_scope': OLD_BLOCK}
                                       for public_id in (SERVICE, SERVER)])
    client[name][RELATIONS].insert_one({'public_id': 1, 'relation_id': RELATION_ID, 'relation_parent_id': SERVICE,
                                        'relation_child_id': SERVER})

    yield name, client[name]

    client.drop_database(name)


def test_every_block_gains_its_related_list(database_manager: MongoDatabaseManager,
                                            scratch: tuple[str, Any]) -> None:
    """Both ends; the version stamped; a second run writes nothing"""
    name, database = scratch

    Update20261129(database_manager, name).start_update()

    blocks = {document['public_id']: document['_scope'] for document in database[OBJECTS].find({}, {'_id': 0})}
    assert blocks == {SERVICE: {**OLD_BLOCK, 'related': [{'object': SERVER, 'relation': RELATION_ID}]},
                      SERVER: {**OLD_BLOCK, 'related': [{'object': SERVICE, 'relation': RELATION_ID}]}}
    assert database['settings.conf'].find_one({'_id': 'updater'})['version'] == 20261129
    assert ObjectScopeBlocks(ObjectsManager(database_manager, name)).refresh([SERVICE, SERVER]) == 0

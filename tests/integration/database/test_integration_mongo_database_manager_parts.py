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
Integration tests of the MongoDatabaseManager's two mixins against a real MongoDB

Everything runs in a scratch database of its own, dropped afterwards. The administration half: a database is created,
found, refused a second time and dropped; a collection is created once and a second create is no error; an index is
built, read back, dropped once and reported absent the second time. The counter half: a counter is seeded from the
highest stored id, peeked without being consumed, drawn, reserved in a block, raised but never lowered by
update_public_id_counter, reset to the highest stored id and set to any value - downwards too
"""
from typing import Iterator

import pytest
from pymongo import ASCENDING, IndexModel

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.errors.database import DatabaseAlreadyExistsError, DatabaseNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-manager-parts'
COLLECTION: str = 'test.managerParts'
INDEX_NAME: str = 'name_index'
STORED_IDS: list[int] = [3, 7, 5]
HIGHEST: int = 7
BLOCK: int = 4
LOWER: int = 2


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A scratch database, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    database_manager.connector.client.drop_database(name)

    yield name

    database_manager.connector.client.drop_database(name)


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, scratch: str) -> str:
    """The scratch database holding documents with STORED_IDS"""
    database_manager.get_collection(COLLECTION, scratch).insert_many([{'public_id': public_id, 'name': str(public_id)}
                                                                       for public_id in STORED_IDS])

    return scratch


def _counter(database_manager: MongoDatabaseManager, db_name: str) -> int | None:
    """The stored counter of COLLECTION"""
    document = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).find_one({'_id': COLLECTION})

    return document['counter'] if document else None


class TestAdministration:
    """MongoDatabaseAdminMixin"""

    def test_a_database_is_created_found_refused_twice_and_dropped(self, database_manager, scratch) -> None:
        """create_database hands out the database; the first write makes it exist"""
        database_manager.create_database(scratch)['probe'].insert_one({'x': 1})

        assert database_manager.check_database_exists(scratch)
        with pytest.raises(DatabaseAlreadyExistsError):
            database_manager.create_database(scratch)

        database_manager.drop_database(scratch)

        assert not database_manager.check_database_exists(scratch)
        with pytest.raises(DatabaseNotFoundError):
            database_manager.drop_database(scratch)

    def test_a_collection_is_created_once(self, database_manager, scratch) -> None:
        """A second create answers the name, no error"""
        assert database_manager.create_collection(COLLECTION, scratch) == COLLECTION
        assert database_manager.create_collection(COLLECTION, scratch) == COLLECTION
        assert COLLECTION in database_manager.connector.client[scratch].list_collection_names()

    def test_an_index_is_built_read_and_dropped_once(self, database_manager, scratch) -> None:
        """drop_index reports False for an index that is not there"""
        database_manager.create_indexes(COLLECTION, scratch, [IndexModel([('name', ASCENDING)], name=INDEX_NAME)])

        assert INDEX_NAME in database_manager.get_index_info(COLLECTION, scratch)
        assert database_manager.drop_index(COLLECTION, scratch, INDEX_NAME) is True
        assert database_manager.drop_index(COLLECTION, scratch, INDEX_NAME) is False

    def test_an_empty_database_name_targets_the_default(self, database_manager) -> None:
        """target_database"""
        assert database_manager.target_database('') == database_manager.db_name


class TestCounters:
    """MongoPublicIdCounterMixin"""

    def test_the_highest_stored_id(self, database_manager, seeded) -> None:
        """0 for an empty collection"""
        assert database_manager.get_highest_id(COLLECTION, seeded) == HIGHEST
        assert database_manager.get_highest_id('test.managerPartsEmpty', seeded) == 0

    def test_a_counter_is_seeded_peeked_and_drawn(self, database_manager, seeded) -> None:
        """A peek consumes nothing; a draw does"""
        assert database_manager.init_public_id_counter(COLLECTION, seeded) == HIGHEST
        assert database_manager.get_next_public_id(COLLECTION, seeded) == HIGHEST + 1
        assert database_manager.get_next_public_id(COLLECTION, seeded) == HIGHEST + 1
        assert database_manager.get_next_public_id(COLLECTION, seeded, inc_id=True) == HIGHEST + 1
        assert _counter(database_manager, seeded) == HIGHEST + 1

    def test_a_block_is_reserved_contiguously(self, database_manager, seeded) -> None:
        """Created when missing"""
        assert database_manager.reserve_public_ids(COLLECTION, seeded, BLOCK) == list(range(1, BLOCK + 1))
        assert database_manager.reserve_public_ids(COLLECTION, seeded, 1) == [BLOCK + 1]

    def test_update_raises_but_never_lowers(self, database_manager, seeded) -> None:
        """The counter only moves forward"""
        database_manager.update_public_id_counter(COLLECTION, seeded, value=HIGHEST)
        database_manager.update_public_id_counter(COLLECTION, seeded, value=LOWER)

        assert _counter(database_manager, seeded) == HIGHEST

        database_manager.update_public_id_counter(COLLECTION, seeded, increment=True)

        assert _counter(database_manager, seeded) == HIGHEST + 1

    def test_reset_and_set_move_downwards_too(self, database_manager, seeded) -> None:
        """reset to the highest stored id, set to exactly the value"""
        database_manager.set_public_id_counter(COLLECTION, seeded, HIGHEST * 10)

        assert database_manager.reset_public_id_counter(COLLECTION, seeded, COLLECTION) == HIGHEST
        assert _counter(database_manager, seeded) == HIGHEST

        database_manager.set_public_id_counter(COLLECTION, seeded, LOWER)

        assert _counter(database_manager, seeded) == LOWER

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
Integration tests for BaseManager.delete_many and delete_many_from_other_collection against a real MongoDB

The filter reaches MongoDB as one dict, so a top-level operator and a field named like one of the method's own
parameters both select what they say. An empty filter would match every document and is refused before the database
is asked - by the cross-collection delete too, unless the caller says it means every document (``delete_all``)
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.deleteManyScratch'
NAME_KEY: str = 'name'
# A stored field that shares its name with a database-layer parameter: a kwargs-spread filter could not carry it
PARAMETER_NAMED_KEY: str = 'collection'
SEEDED_NAMES: list[str] = ['a', 'b', 'c', 'd']
# The collection of the manager that reaches into the seeded one - never written
OTHER_OWNER_COLLECTION: str = 'test.deleteManyOwner'


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A BaseManager on a seeded scratch collection, dropped afterwards"""
    collection = database_manager.get_collection(COLLECTION, database_name)
    collection.insert_many([
        {'public_id': index + 1, NAME_KEY: name, PARAMETER_NAMED_KEY: f'group-{index % 2}'}
        for index, name in enumerate(SEEDED_NAMES)
    ])

    yield BaseManager(COLLECTION, database_manager, database_name)

    collection.drop()


def _remaining(database_manager: MongoDatabaseManager, database_name: str) -> list[str]:
    """The names still stored, sorted"""
    return sorted(document[NAME_KEY] for document in database_manager.get_collection(COLLECTION, database_name).find())


def test_a_top_level_or_deletes_what_it_names(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """An operator-keyed filter is handed over whole"""
    result = manager.delete_many({'$or': [{NAME_KEY: 'a'}, {NAME_KEY: 'c'}]})

    assert result.deleted_count == 2
    assert _remaining(database_manager, database_name) == ['b', 'd']


def test_a_field_named_like_a_parameter_is_a_plain_filter_field(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """'collection' selects documents by that field - it no longer collides with the method's own argument"""
    result = manager.delete_many({PARAMETER_NAMED_KEY: 'group-1'})

    assert result.deleted_count == 2
    assert _remaining(database_manager, database_name) == ['a', 'c']


def test_an_empty_filter_is_refused_and_nothing_is_deleted(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The whole collection survives"""
    with pytest.raises(BaseManagerDeleteError):
        manager.delete_many({})

    assert _remaining(database_manager, database_name) == SEEDED_NAMES


class TestTheCrossCollectionDelete:
    """The same guard on the delete in another collection, run here from a manager of a different one"""

    @pytest.fixture(name='other_manager')
    def fixture_other_manager(self, manager: BaseManager, database_manager: MongoDatabaseManager,
                              database_name: str) -> BaseManager:
        """A manager owning another collection, reaching into the seeded one"""
        return BaseManager(OTHER_OWNER_COLLECTION, database_manager, database_name)

    def test_an_empty_filter_is_refused_and_nothing_is_deleted(
            self, other_manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The other collection survives a filter that came out empty"""
        with pytest.raises(BaseManagerDeleteError):
            other_manager.delete_many_from_other_collection(COLLECTION, {})

        assert _remaining(database_manager, database_name) == SEEDED_NAMES

    def test_delete_all_empties_the_collection(
            self, other_manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The deliberate full delete, named at the call"""
        result = other_manager.delete_many_from_other_collection(COLLECTION, {}, delete_all=True)

        assert result.deleted_count == len(SEEDED_NAMES)
        assert not _remaining(database_manager, database_name)

    def test_a_filter_deletes_only_what_it_names(
            self, other_manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """delete_all is not needed - nor read - when there is a filter"""
        result = other_manager.delete_many_from_other_collection(COLLECTION, {NAME_KEY: 'b'})

        assert result.deleted_count == 1
        assert _remaining(database_manager, database_name) == ['a', 'c', 'd']

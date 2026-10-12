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
Integration tests for cmdb.database.updater.versions.updater_20261014 against a real MongoDB

Seeds three relations sharing one name, one whose renamed form is already taken, and a near-twin in another case,
with the unique index dropped as on a database the rule has not reached yet; runs the migration and asserts:
  - the lowest public_id keeps the name, the others are renamed ``<name>-<public_id>`` (again when taken)
  - the near-twin is left alone; nothing but the name changes
  - the unique index is in place afterwards and refuses a duplicate
  - a second run changes nothing
"""
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261014 import Update20261014
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.relation_model.relation_constants import RelationKey
# -------------------------------------------------------------------------------------------------------------------- #

NAME: str = RelationKey.RELATION_NAME.value
PUBLIC_ID: str = RelationKey.PUBLIC_ID.value
KEEPER_ID: int = 98701
SECOND_ID: int = 98702
THIRD_ID: int = 98703
TAKEN_ID: int = 98704
TWIN_ID: int = 98705
SHARED: str = 'upd-runs-on'
SEEDED: dict[int, str] = {
    THIRD_ID: SHARED, KEEPER_ID: SHARED, SECOND_ID: SHARED,
    TAKEN_ID: f'{SHARED}-{SECOND_ID}', TWIN_ID: SHARED.upper(),
}
EXPECTED: dict[int, str] = {
    KEEPER_ID: SHARED, SECOND_ID: f'{SHARED}-{SECOND_ID}-{SECOND_ID}', THIRD_ID: f'{SHARED}-{THIRD_ID}',
    TAKEN_ID: f'{SHARED}-{SECOND_ID}', TWIN_ID: SHARED.upper(),
}


@pytest.fixture(name='relations')
def fixture_relations(database_manager: MongoDatabaseManager, database_name: str):
    """The relation collection without its unique name index, holding the seeded duplicates; restored afterwards"""
    collection = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    collection.delete_many({PUBLIC_ID: {'$in': list(SEEDED)}})

    had_index: bool = NAME in collection.index_information()

    if had_index:
        collection.drop_index(NAME)

    collection.insert_many([{PUBLIC_ID: public_id, NAME: name, 'description': f'kept-{public_id}'}
                            for public_id, name in SEEDED.items()])
    yield collection
    collection.delete_many({PUBLIC_ID: {'$in': list(SEEDED)}})

    # Leave the index as the session had it: the run built it
    if not had_index and NAME in collection.index_information():
        collection.drop_index(NAME)


def _names(relations) -> dict[int, Any]:
    """The seeded relations' names by public_id."""
    return {row[PUBLIC_ID]: row[NAME] for row in relations.find({PUBLIC_ID: {'$in': list(SEEDED)}})}


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration."""
    Update20261014(database_manager, database_name).start_update()


def test_the_duplicates_are_renamed_and_the_rest_left(database_manager, database_name, relations) -> None:
    """Only the name changes"""
    _run(database_manager, database_name)

    assert _names(relations) == EXPECTED
    assert {row[PUBLIC_ID]: row['description'] for row in relations.find({PUBLIC_ID: {'$in': list(SEEDED)}})} == {
        public_id: f'kept-{public_id}' for public_id in SEEDED}


def test_the_unique_index_is_built_and_refuses_a_duplicate(database_manager, database_name, relations) -> None:
    """The guarantee the routes rely on"""
    _run(database_manager, database_name)

    assert relations.index_information()[NAME].get('unique') is True
    with pytest.raises(DuplicateKeyError):
        relations.insert_one({PUBLIC_ID: TWIN_ID + 1, NAME: SHARED})


def test_a_second_run_changes_nothing(database_manager, database_name, relations) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    _run(database_manager, database_name)

    assert _names(relations) == EXPECTED

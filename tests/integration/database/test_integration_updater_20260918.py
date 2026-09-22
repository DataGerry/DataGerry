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
Integration tests for cmdb.database.updater.versions.updater_20260918 against a real MongoDB

Reproduces a pre-migration database - CmdbTypes carrying no 'port_section_index' key at all - and
asserts the backfill lands on every one of them, that a type which already carries a position keeps
it, and that a second run changes nothing.

The "keeps its position" case is the one that needs a real collection: a port-bearing type set up
between the release and the migration has a placement its user made, and a filter that matched it
would silently move that panel back to the top.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20260918 import Update20260918
from cmdb.models.type_model import CmdbType, DEFAULT_PORT_SECTION_INDEX, TypeSchemaKey
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

# Types seeded without the key - the state every type is in before this migration
LEGACY_TYPE_ID: int = 9940
SECOND_LEGACY_TYPE_ID: int = 9941
# A port-bearing type whose placement was made before the migration ran and must survive it
PLACED_TYPE_ID: int = 9942
# A type already carrying the default, which the backfill has no reason to rewrite
ALREADY_DEFAULT_TYPE_ID: int = 9943

ALL_TYPE_IDS: list[int] = [
    LEGACY_TYPE_ID,
    SECOND_LEGACY_TYPE_ID,
    PLACED_TYPE_ID,
    ALREADY_DEFAULT_TYPE_ID,
]

PLACED_INDEX: int = 3


@pytest.fixture(name='pre_migration_types', autouse=True)
def fixture_pre_migration_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the four type shapes the migration has to tell apart, cleaning up after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({TypeSchemaKey.PUBLIC_ID.value: {'$in': ALL_TYPE_IDS}})

    _purge()

    legacy_one = make_type_doc(LEGACY_TYPE_ID, 'index-legacy-one')
    legacy_two = make_type_doc(SECOND_LEGACY_TYPE_ID, 'index-legacy-two')
    placed = make_type_doc(PLACED_TYPE_ID, 'index-placed')
    already_default = make_type_doc(ALREADY_DEFAULT_TYPE_ID, 'index-already-default')

    # make_type_doc predates the key, which is exactly the pre-migration shape
    for doc in (legacy_one, legacy_two):
        assert TypeSchemaKey.PORT_SECTION_INDEX.value not in doc

    placed[TypeSchemaKey.USES_PORTS.value] = True
    placed[TypeSchemaKey.PORT_SECTION_INDEX.value] = PLACED_INDEX
    already_default[TypeSchemaKey.PORT_SECTION_INDEX.value] = DEFAULT_PORT_SECTION_INDEX

    types.insert_many([legacy_one, legacy_two, placed, already_default])

    yield

    _purge()


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260918(database_manager, database_name).start_update()


def _type(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded CmdbType back"""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .find_one({TypeSchemaKey.PUBLIC_ID.value: public_id})


class TestTheBackfill:
    """Every CmdbType ends up carrying a position."""

    def test_a_type_without_the_key_gets_the_default(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The state every type in an existing installation is in."""
        _run_migration(database_manager, database_name)

        for public_id in (LEGACY_TYPE_ID, SECOND_LEGACY_TYPE_ID):
            stored = _type(database_manager, database_name, public_id)

            assert stored[TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX

    def test_a_type_that_does_not_use_ports_is_backfilled_too(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        The key is part of a CmdbType's shape, not of the ports feature

        A type that opts into ports later must not have to acquire the key first, and a query
        filtering or sorting on it must not silently skip the types that never got it.
        """
        _run_migration(database_manager, database_name)

        stored = _type(database_manager, database_name, LEGACY_TYPE_ID)

        assert stored.get(TypeSchemaKey.USES_PORTS.value) is None
        assert TypeSchemaKey.PORT_SECTION_INDEX.value in stored

    def test_an_existing_placement_survives(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A position placed between the release and the migration is the user's, not the default's."""
        _run_migration(database_manager, database_name)

        stored = _type(database_manager, database_name, PLACED_TYPE_ID)

        assert stored[TypeSchemaKey.PORT_SECTION_INDEX.value] == PLACED_INDEX


class TestTheRerun:
    """The migration is re-run safe, which is what an interrupted first run needs."""

    def test_a_second_run_modifies_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """`$exists: False` matches nothing once every type carries the key."""
        _run_migration(database_manager, database_name)
        _run_migration(database_manager, database_name)

        stored = {public_id: _type(database_manager, database_name, public_id)
                  for public_id in ALL_TYPE_IDS}

        assert stored[LEGACY_TYPE_ID][TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX
        assert stored[PLACED_TYPE_ID][TypeSchemaKey.PORT_SECTION_INDEX.value] == PLACED_INDEX

    def test_an_interrupted_run_resumes(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        A partially backfilled database is finished off without touching what is already done

        Simulated by backfilling one type by hand before the migration runs - the same state a crash
        mid-write leaves behind, because the update is applied document by document.
        """
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.update_one(
            {TypeSchemaKey.PUBLIC_ID.value: LEGACY_TYPE_ID},
            {'$set': {TypeSchemaKey.PORT_SECTION_INDEX.value: DEFAULT_PORT_SECTION_INDEX}},
        )

        _run_migration(database_manager, database_name)

        for public_id in (LEGACY_TYPE_ID, SECOND_LEGACY_TYPE_ID):
            stored = _type(database_manager, database_name, public_id)

            assert stored[TypeSchemaKey.PORT_SECTION_INDEX.value] == DEFAULT_PORT_SECTION_INDEX

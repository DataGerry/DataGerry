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
Integration tests for the DataGerry Assistant run against a real MongoDB

  - a real run records every type and category it stores in the ledger, with the caller as the types' author;
    undoing the ledger deletes all of them
  - a run whose category insert fails, undone the way the route undoes it, leaves no type behind
  - the one-time marker: of two claims of the same settings section exactly one wins; a deleted section can be
    claimed again
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CategoriesManager, SectionTemplatesManager, SettingsManager, TypesManager
from cmdb.models.category_model import CmdbCategory
from cmdb.models.type_model import CmdbType
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant
from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.framework.write_ledger import WriteLedger

from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 88801
MARKER_SECTION: str = 'assistant-integration-marker'
PROFILES: list[str] = [ProfileName.USER_MANAGEMENT.value]


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The type and category collections; every document newer than the test is deleted after it"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
    before_types = [doc['public_id'] for doc in types.find({}, {'public_id': 1})]
    before_categories = [doc['public_id'] for doc in categories.find({}, {'public_id': 1})]

    def _new() -> dict[str, list[dict[str, Any]]]:
        return {'types': list(types.find({'public_id': {'$nin': before_types}})),
                'categories': list(categories.find({'public_id': {'$nin': before_categories}}))}

    yield _new
    types.delete_many({'public_id': {'$nin': before_types}})
    categories.delete_many({'public_id': {'$nin': before_categories}})


def _assistant(database_manager: MongoDatabaseManager, ledger: WriteLedger,
               categories_manager: CategoriesManager | None = None) -> ProfileAssistant:
    """A ProfileAssistant on the test database"""
    return ProfileAssistant(categories_manager or CategoriesManager(database_manager), TypesManager(database_manager),
                            SectionTemplatesManager(database_manager), author_id=AUTHOR_ID, ledger=ledger)


class TestTheRun:
    """What a run stores, and its undo"""

    def test_a_run_records_what_it_stores_and_the_undo_removes_it(self, database_manager, collections) -> None:
        """Types (authored by the caller) and categories, then nothing"""
        ledger = WriteLedger()

        created_ids = _assistant(database_manager, ledger).create_profiles(PROFILES)

        stored = collections()
        assert sorted(created_ids) == sorted(doc['public_id'] for doc in stored['types'])
        assert {doc['author_id'] for doc in stored['types']} == {AUTHOR_ID}
        assert len(ledger.entries) == len(stored['types']) + len(stored['categories'])

        assert ledger.undo() == []
        assert collections() == {'types': [], 'categories': []}

    def test_a_failed_category_insert_is_undone_to_nothing(self, database_manager, collections) -> None:
        """The route's path: the error surfaces, the ledger undoes every type stored before it"""
        ledger = WriteLedger()
        failing_categories = CategoriesManager(database_manager)
        failing_categories.insert_category = lambda _category: (_ for _ in ()).throw(RuntimeError('down'))

        with pytest.raises(ProfileCreationError):
            _assistant(database_manager, ledger, failing_categories).create_profiles(PROFILES)

        assert collections()['types']
        assert ledger.undo() == []
        assert collections() == {'types': [], 'categories': []}


class TestTheMarker:
    """SettingsManager.claim_section on the real unique _id"""

    @pytest.fixture(name='settings')
    def fixture_settings(self, database_manager: MongoDatabaseManager, database_name: str):
        """A SettingsManager, the marker removed around the test"""
        manager = SettingsManager(database_manager, database_name)
        manager.delete_section(MARKER_SECTION)
        yield manager
        manager.delete_section(MARKER_SECTION)

    def test_exactly_one_of_two_claims_wins(self, settings: SettingsManager) -> None:
        """The second insert is refused by the _id index"""
        assert [settings.claim_section(MARKER_SECTION, {'claimed_by': run}) for run in (1, 2)] == [True, False]
        assert settings.get_section(MARKER_SECTION)['claimed_by'] == 1

    def test_a_released_section_can_be_claimed_again(self, settings: SettingsManager) -> None:
        """What lets the assistant run again after an undone run"""
        settings.claim_section(MARKER_SECTION, {})

        assert settings.delete_section(MARKER_SECTION) is True
        assert settings.claim_section(MARKER_SECTION, {}) is True

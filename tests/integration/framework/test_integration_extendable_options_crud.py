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
Integration tests for the CmdbExtendableOption CRUD surface of ExtendableOptionsManager

Pins the manager-layer behaviour against a real MongoDB: insert / get / update / delete round-trip
through the bound collection and iterate_items honours BuilderParameters. ExtendableOptionsManager
is a thin GenericManager subclass, so this exercises the generic CRUD wiring for the option
collection.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
# -------------------------------------------------------------------------------------------------------------------- #

OPTION_ID_FOR_INSERT: int = 9811
OPTION_ID_FOR_GET: int = 9812
OPTION_ID_FOR_UPDATE: int = 9813
OPTION_ID_FOR_DELETE: int = 9814
OPTION_ID_FOR_ITERATE_A: int = 9815
OPTION_ID_FOR_ITERATE_B: int = 9816
MISSING_OPTION_ID: int = 9899

ORIGINAL_VALUE: str = 'Integration Option'
UPDATED_VALUE: str = 'Integration Option (updated)'

SEED_OPTION_IDS: list[int] = [
    OPTION_ID_FOR_INSERT,
    OPTION_ID_FOR_GET,
    OPTION_ID_FOR_UPDATE,
    OPTION_ID_FOR_DELETE,
    OPTION_ID_FOR_ITERATE_A,
    OPTION_ID_FOR_ITERATE_B,
]


def _option_data(public_id: int, value: str = ORIGINAL_VALUE) -> dict[str, Any]:
    """Builds a minimal CmdbExtendableOption document acceptable to insert_item."""
    return {
        'public_id': public_id,
        'value': value,
        'option_type': OptionType.RISK.value,
        'predefined': False,
    }


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the extendable-option collection bound to the test database."""
    return database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _collection(database_manager, database_name).delete_many({'public_id': {'$in': SEED_OPTION_IDS}})


@pytest.fixture(name='extendable_options_manager')
def fixture_extendable_options_manager(database_manager: MongoDatabaseManager) -> ExtendableOptionsManager:
    """Provides an ExtendableOptionsManager wired to the test database."""
    return ExtendableOptionsManager(database_manager)


def _delete_option(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one option doc directly via the collection, used for per-test cleanup."""
    _collection(database_manager, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertExtendableOption:
    """``insert_item`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_INSERT))

            assert returned_id == OPTION_ID_FOR_INSERT
            stored = _collection(database_manager, database_name).find_one({'public_id': OPTION_ID_FOR_INSERT})
            assert stored is not None
            assert stored['value'] == ORIGINAL_VALUE
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetExtendableOption:
    """``get_item`` resolves present ids and returns None for missing ones."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single option before each test in this class and removes it after."""
        extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_GET))
        yield
        _delete_option(database_manager, database_name, OPTION_ID_FOR_GET)

    def test_returns_dict_for_existing_id(self, extendable_options_manager: ExtendableOptionsManager) -> None:
        """A present id resolves into a dict carrying the seeded public_id."""
        result = extendable_options_manager.get_item(OPTION_ID_FOR_GET, as_dict=True)

        assert result is not None
        assert result['public_id'] == OPTION_ID_FOR_GET

    def test_returns_none_for_missing_id(self, extendable_options_manager: ExtendableOptionsManager) -> None:
        """A missing id returns None."""
        assert extendable_options_manager.get_item(MISSING_OPTION_ID, as_dict=True) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateExtendableOption:
    """``update_item`` writes the new payload over the existing doc."""

    def test_persists_new_value(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing option replaces the stored value."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_UPDATE))

            extendable_options_manager.update_item(
                OPTION_ID_FOR_UPDATE, _option_data(OPTION_ID_FOR_UPDATE, UPDATED_VALUE)
            )

            stored = extendable_options_manager.get_item(OPTION_ID_FOR_UPDATE, as_dict=True)
            assert stored is not None
            assert stored['value'] == UPDATED_VALUE
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteExtendableOption:
    """``delete_item`` removes the document and reports the acknowledgement."""

    def test_removes_doc(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing option removes it and returns True."""
        extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_DELETE))

        assert extendable_options_manager.delete_item(OPTION_ID_FOR_DELETE) is True
        assert _collection(database_manager, database_name).find_one({'public_id': OPTION_ID_FOR_DELETE}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ITERATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterateExtendableOptions:
    """``iterate_items`` returns the matching options with a total count."""

    def test_iterate_returns_seeded_rows(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A filter on public_id returns exactly the matching seeded options."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_ITERATE_A, 'Iter A'))
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_ITERATE_B, 'Iter B'))

            builder_params = BuilderParameters(
                criteria={'public_id': {'$in': [OPTION_ID_FOR_ITERATE_A, OPTION_ID_FOR_ITERATE_B]}}
            )
            result = extendable_options_manager.iterate_items(builder_params)

            assert result.total == 2
            assert {option.get_public_id() for option in result.results} == {
                OPTION_ID_FOR_ITERATE_A, OPTION_ID_FOR_ITERATE_B,
            }
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_ITERATE_A)
            _delete_option(database_manager, database_name, OPTION_ID_FOR_ITERATE_B)

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

Its three own reads are pinned here too, because what they answer depends on the stored document
rather than on the model: the value snapshot (`get_option_values`), the public_id -> value lookup a
report resolves labels through (`get_option_values_by_id`), and the raw documents the list route
sends (`iterate_option_documents`). Also pinned: a model read back through `get_item` really does
carry the stored values - the model shares `CmdbDAO.from_data` / `to_json` since 2026-09-10.
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
OPTION_ID_FOR_LOOKUP_A: int = 9817
OPTION_ID_FOR_LOOKUP_B: int = 9818
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
    OPTION_ID_FOR_LOOKUP_A,
    OPTION_ID_FOR_LOOKUP_B,
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


class TestGetItemBuildsTheModel:
    """``get_item`` reads a stored document back through the shared from_data."""

    def test_the_stored_values_survive_the_read(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The model is what the update route compares its payload against, so it must be faithful."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_GET, 'model-read'))

            option = extendable_options_manager.get_item(OPTION_ID_FOR_GET)

            assert isinstance(option, CmdbExtendableOption)
            assert option.get_public_id() == OPTION_ID_FOR_GET
            assert option.value == 'model-read'
            assert option.option_type == OptionType.RISK.value
            assert option.predefined is False
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_GET)

    def test_a_document_without_the_predefined_flag_reads_as_not_predefined(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The flag is two-state, and only an insert through the schema is guaranteed to carry it

        A document written directly (the ISMS importer, a seeder, an older version) may not, and the
        update and delete guards both read it.
        """
        try:
            _collection(database_manager, database_name).insert_one({
                'public_id': OPTION_ID_FOR_GET,
                'value': 'flagless',
                'option_type': OptionType.RISK.value,
            })

            assert extendable_options_manager.get_item(OPTION_ID_FOR_GET).predefined is False
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_GET)


class TestGetOptionValuesById:
    """The public_id -> value lookup, over the real (option_type, value) index."""

    def test_it_groups_the_requested_lists(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Two lists come back from one read, apart, keyed by the ids a report references."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_LOOKUP_A, 'Lookup Risk'))
            extendable_options_manager.insert_item({
                'public_id': OPTION_ID_FOR_LOOKUP_B,
                'value': 'Lookup State',
                'option_type': OptionType.IMPLEMENTATION_STATE.value,
                'predefined': False,
            })

            value_maps = extendable_options_manager.get_option_values_by_id(
                [OptionType.RISK.value, OptionType.IMPLEMENTATION_STATE.value]
            )

            assert value_maps[OptionType.RISK.value][OPTION_ID_FOR_LOOKUP_A] == 'Lookup Risk'
            assert value_maps[OptionType.IMPLEMENTATION_STATE.value][OPTION_ID_FOR_LOOKUP_B] == 'Lookup State'
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_LOOKUP_A)
            _delete_option(database_manager, database_name, OPTION_ID_FOR_LOOKUP_B)

    def test_an_unrequested_option_type_is_not_read(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A label from another dropdown resolving would put a wrong value in a report."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_LOOKUP_A, 'Lookup Risk'))

            value_maps = extendable_options_manager.get_option_values_by_id(
                [OptionType.IMPLEMENTATION_STATE.value]
            )

            assert OptionType.RISK.value not in value_maps
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_LOOKUP_A)


class TestIterateOptionDocuments:
    """The list route's read: documents and a total, with no model built."""

    def test_it_answers_documents_and_the_total(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The documents are what the route normalises; the total is what the envelope carries."""
        try:
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_ITERATE_A, 'Iter A'))
            extendable_options_manager.insert_item(_option_data(OPTION_ID_FOR_ITERATE_B, 'Iter B'))

            documents, total = extendable_options_manager.iterate_option_documents(BuilderParameters(
                criteria={'public_id': {'$in': [OPTION_ID_FOR_ITERATE_A, OPTION_ID_FOR_ITERATE_B]}}
            ))

            assert total == 2
            assert all(isinstance(document, dict) for document in documents)
            assert {document['public_id'] for document in documents} == {
                OPTION_ID_FOR_ITERATE_A, OPTION_ID_FOR_ITERATE_B,
            }
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_ITERATE_A)
            _delete_option(database_manager, database_name, OPTION_ID_FOR_ITERATE_B)

    def test_a_drifted_document_still_reaches_the_caller(
        self,
        extendable_options_manager: ExtendableOptionsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The read does not judge the documents - the route's normalisation does

        Which is what makes one unreadable option a skipped row rather than a failed read.
        """
        try:
            _collection(database_manager, database_name).insert_one({
                'public_id': OPTION_ID_FOR_ITERATE_A,
                'option_type': OptionType.RISK.value,
            })

            documents, total = extendable_options_manager.iterate_option_documents(BuilderParameters(
                criteria={'public_id': OPTION_ID_FOR_ITERATE_A}
            ))

            assert total == 1
            assert documents[0]['public_id'] == OPTION_ID_FOR_ITERATE_A
        finally:
            _delete_option(database_manager, database_name, OPTION_ID_FOR_ITERATE_A)

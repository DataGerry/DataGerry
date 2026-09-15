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
Unit tests for cmdb.database.updater.versions.updater_20260909

Covers the pieces in isolation with a stubbed database manager: the filter that is the whole of the
migration's re-run safety, the set of collections and keys it touches, and start_update's
orchestration + error wrapping.

The end-to-end behaviour against a real MongoDB - including the double run and the data it must not
touch - is covered by tests/integration/database/test_integration_updater_20260909.py, and the metadata
contract by the shared parametrized test in test_version_updaters
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260909 import (
    NULLABLE_KEYS_BY_COLLECTION,
    PERSON_COLLECTION,
    PERSON_GROUP_COLLECTION,
    Update20260909,
    build_unset_or_null_criteria,
)
from cmdb.models.person_model import CmdbPerson, PERSON_LIST_KEYS, PERSON_OPTIONAL_TEXT_KEYS
from cmdb.models.person_group_model import (
    CmdbPersonGroup,
    PERSON_GROUP_LIST_KEYS,
    PERSON_GROUP_OPTIONAL_TEXT_KEYS,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.updater.versions.updater_20260909'
DB_NAME: str = 'testdb'


def _updater(modified: int = 0) -> Any:
    """
    Builds the updater with a stubbed database manager, bypassing the base class's wiring

    BaseDatabaseUpdate.__init__ reads the config and opens a MongoDatabaseManager, so the instance is
    created through __new__ and given the two attributes this migration touches.

    Args:
        modified (int): modified_count each update reports

    Returns:
        Any: The updater, with a stubbed dbm and a stubbed version bump
    """
    updater = Update20260909.__new__(Update20260909)
    updater.dbm = MagicMock()
    updater.dbm.update_many.return_value = MagicMock(modified_count=modified)
    updater.db_name = DB_NAME
    updater.settings_manager = MagicMock()

    return updater


class TestScope:
    """Which collections and keys the migration covers."""

    def test_covers_both_membership_collections(self) -> None:
        """The two collections whose models used to write null."""
        assert set(NULLABLE_KEYS_BY_COLLECTION) == {PERSON_COLLECTION, PERSON_GROUP_COLLECTION}

    def test_the_collection_names_match_the_models(self) -> None:
        """
        The names are frozen locally, as a migration's literals must be

        Frozen does not mean free to be wrong: this is the one assertion tying them to the models,
        and it lives in the test rather than in the migration on purpose.
        """
        assert PERSON_COLLECTION == CmdbPerson.COLLECTION
        assert PERSON_GROUP_COLLECTION == CmdbPersonGroup.COLLECTION

    def test_covers_every_key_the_models_coerce(self) -> None:
        """
        A key the model stops writing null for, but the migration never converged, stays null forever

        The two lists are declared independently - the model's for reads, the migration's frozen copy
        for this one-off write - so they are compared here.
        """
        assert set(NULLABLE_KEYS_BY_COLLECTION[PERSON_COLLECTION]) == set(
            PERSON_OPTIONAL_TEXT_KEYS + PERSON_LIST_KEYS
        )
        assert set(NULLABLE_KEYS_BY_COLLECTION[PERSON_GROUP_COLLECTION]) == set(
            PERSON_GROUP_OPTIONAL_TEXT_KEYS + PERSON_GROUP_LIST_KEYS
        )

    def test_text_keys_become_empty_strings_and_list_keys_empty_lists(self) -> None:
        """The empty value has to match what the model would write for the same key."""
        person_keys: dict[str, Any] = NULLABLE_KEYS_BY_COLLECTION[PERSON_COLLECTION]

        for key in PERSON_OPTIONAL_TEXT_KEYS:
            assert person_keys[key] == ''

        for key in PERSON_LIST_KEYS:
            assert person_keys[key] == []


class TestSelection:
    """The filter, which is the whole of the re-run safety."""

    def test_selects_the_null_and_the_absent_key(self) -> None:
        """The two states this migration exists for, and only those."""
        assert build_unset_or_null_criteria('email') == {
            '$or': [{'email': None}, {'email': {'$exists': False}}],
        }

    def test_neither_arm_can_match_a_key_that_already_holds_an_empty_value(self) -> None:
        """
        What makes a second run a no-op

        The equality arm asks for null and '' is not null; the existence arm asks for the key to be
        absent and it is present. Whether MongoDB agrees is asserted against a real database in the
        integration module - here the shape is pinned, since a filter of {'email': {'$in': [None, '']}}
        would look just as reasonable and would rewrite every converged document on every start.
        """
        equality_arm, existence_arm = build_unset_or_null_criteria('email')['$or']

        assert equality_arm['email'] is None
        assert existence_arm['email'] == {'$exists': False}


class TestStartUpdate:
    """The orchestration: every key of both collections, then the version bump."""

    def test_normalises_every_declared_key_before_bumping_the_version(self) -> None:
        """
        One update per key, and the version bumped only after all of them

        An interrupted run therefore keeps its version, so the next start repeats the whole
        migration - which is safe precisely because the filter is narrow.
        """
        updater = _updater()
        expected_calls = sum(len(keys) for keys in NULLABLE_KEYS_BY_COLLECTION.values())

        updater.start_update()

        assert updater.dbm.update_many.call_count == expected_calls
        updater.settings_manager.write.assert_called_once()

    def test_writes_the_empty_value_into_the_matched_key(self) -> None:
        """Each update sets exactly the one key it selected on."""
        updater = _updater()

        updater.start_update()

        for call in updater.dbm.update_many.call_args_list:
            collection, db_name, criteria, update = call.args

            (key,) = update.keys()

            assert db_name == DB_NAME
            assert criteria == build_unset_or_null_criteria(key)
            assert update[key] == NULLABLE_KEYS_BY_COLLECTION[collection][key]

    def test_logs_nothing_for_a_database_that_needs_no_change(self) -> None:
        """A re-run is silent, which is what an operator should see the second time."""
        updater = _updater(modified=0)

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            updater.start_update()

        mock_logger.info.assert_not_called()

    def test_logs_the_count_per_key_that_changed(self) -> None:
        """A migration that silently did nothing would otherwise look like one that worked."""
        updater = _updater(modified=2)

        with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
            updater.start_update()

        assert mock_logger.info.call_count == sum(
            len(keys) for keys in NULLABLE_KEYS_BY_COLLECTION.values()
        )

    def test_wraps_a_failure_and_leaves_the_version_alone(self) -> None:
        """
        The version is not bumped when an update fails, so the next start retries

        Recording it as complete would leave the remaining documents null forever.
        """
        updater = _updater()
        updater.dbm.update_many.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.settings_manager.write.assert_not_called()

    def test_the_original_error_survives_as_the_cause(self) -> None:
        """A wrapper that keeps only the text loses the pymongo error's type and detail."""
        updater = _updater()
        original = RuntimeError('boom')
        updater.dbm.update_many.side_effect = original

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        assert caught.value.__cause__ is original
        assert caught.value.args[0] is original

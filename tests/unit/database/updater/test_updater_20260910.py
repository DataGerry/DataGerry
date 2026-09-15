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
Unit tests for cmdb.database.updater.versions.updater_20260910

Covers the migration's own decisions with a stubbed database manager: which collection and which keys
it touches, that it reuses the conversion of updater_20260907 rather than carrying a second copy of
that pipeline, and start_update's orchestration + error wrapping.

The conversion itself is MongoDB's work, so the end-to-end behaviour - including the double run and the
values it must not destroy - is covered by
tests/integration/database/test_integration_updater_20260910.py, and the metadata contract by the
shared parametrized test in test_version_updaters
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260910 import (
    OBJECT_RELATION_COLLECTION,
    OBJECT_RELATION_DATE_FIELDS,
    Update20260910,
)
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.updater.versions.updater_20260910'
DB_NAME: str = 'testdb'


def _updater() -> Update20260910:
    """
    Builds the updater with a stubbed database manager, bypassing the base class's wiring

    BaseDatabaseUpdate.__init__ reads the config and opens a MongoDatabaseManager, so the instance is
    created through __new__ and given the attributes this migration touches.

    Returns:
        Update20260910: The updater, with a stubbed dbm and a stubbed version bump
    """
    updater = Update20260910.__new__(Update20260910)
    updater.dbm = MagicMock()
    updater.db_name = DB_NAME
    updater.settings_manager = MagicMock()

    return updater


class TestScope:
    """What the migration touches."""

    def test_targets_the_object_relation_collection(self) -> None:
        """Frozen locally, as a migration's literals must be - and checked against the model here."""
        assert OBJECT_RELATION_COLLECTION == CmdbObjectRelation.COLLECTION

    def test_covers_both_timestamps(self) -> None:
        """
        'creation_time' is included although no writer is known to have wrapped it

        A document restored from an old dump would be indistinguishable, and converting a key that
        already holds a date costs nothing: the type filter does not match it.
        """
        assert set(OBJECT_RELATION_DATE_FIELDS) == set(CmdbObjectRelation.DATE_FIELDS)


class TestStartUpdate:
    """The orchestration: both keys, then the version bump."""

    def test_converts_both_keys_before_bumping_the_version(self) -> None:
        """An interrupted run keeps its version, so the next start repeats the whole migration."""
        updater = _updater()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=1) as mock_convert:
            updater.start_update()

        converted_fields = [call.args[3] for call in mock_convert.call_args_list]

        assert converted_fields == list(OBJECT_RELATION_DATE_FIELDS)
        updater.settings_manager.write.assert_called_once()

    def test_uses_the_shared_conversion_of_the_sibling_migration(self) -> None:
        """
        One implementation of the pipeline, not a frozen second copy

        Its subtle parts - reaching a key that starts with '$' through $getField/$literal, and the two
        fallback arms that keep an unreadable value from being nulled - are worth having in one place.
        """
        updater = _updater()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=0) as mock_convert:
            updater.start_update()

        for call in mock_convert.call_args_list:
            assert call.args[0] is updater.dbm
            assert call.args[1] == DB_NAME
            assert call.args[2] == OBJECT_RELATION_COLLECTION

    def test_logs_nothing_for_a_database_that_needs_no_conversion(self) -> None:
        """A re-run is silent, which is what an operator should see the second time."""
        updater = _updater()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=0):
            with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
                updater.start_update()

        mock_logger.info.assert_not_called()

    def test_logs_the_count_per_converted_key(self) -> None:
        """A migration that silently did nothing would otherwise look like one that worked."""
        updater = _updater()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', return_value=4):
            with patch(f'{MODULE_PATH}.LOGGER') as mock_logger:
                updater.start_update()

        assert mock_logger.info.call_count == len(OBJECT_RELATION_DATE_FIELDS)

    def test_wraps_a_failure_and_leaves_the_version_alone(self) -> None:
        """Recording the version after a failed conversion would leave the rest wrapped forever."""
        updater = _updater()

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', side_effect=RuntimeError('boom')):
            with pytest.raises(UpdaterException):
                updater.start_update()

        updater.settings_manager.write.assert_not_called()

    def test_the_original_error_survives_as_the_cause(self) -> None:
        """A wrapper that keeps only the text loses the pymongo error's type and detail."""
        updater = _updater()
        original = RuntimeError('boom')

        with patch(f'{MODULE_PATH}.convert_wrapped_dates', side_effect=original):
            with pytest.raises(UpdaterException) as caught:
                updater.start_update()

        assert caught.value.__cause__ is original
        assert caught.value.args[0] is original

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
Unit tests for cmdb.database.updater.versions.updater_20260918

The migration gives every CmdbType written before `port_section_index` existed the default position
of the ports section.

One collection, one query - so what is worth pinning is the query itself: it selects on the ABSENCE
of the key, which is what makes a re-run a no-op and what keeps a type that already carries a
position (including one placed between the release and the migration) from being reset to 0.

The end-to-end behaviour and the double run are covered by the integration tier
"""
import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260918 import Update20260918
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.models.type_model import DEFAULT_PORT_SECTION_INDEX, TypeSchemaKey
from tests.unit.database.updater.test_updater_version_bump_contract import (
    build_stubbed_updater,
)
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20260918
PORT_SECTION_INDEX_KEY: str = TypeSchemaKey.PORT_SECTION_INDEX.value


class TestTheQueryIsTheMigration:
    """One update_many on the types, filtered on the absence of the key."""

    def test_only_types_missing_the_key_are_selected(self) -> None:
        """
        The filter is what makes the migration idempotent AND non-destructive

        `$exists: False` matches nothing on a second run, and a type that already carries a position
        - whichever one - is never touched, so a port-bearing type set up between the release and
        this migration keeps the placement its user made.
        """
        updater = build_stubbed_updater(Update20260918)

        updater.start_update()

        assert updater.types_manager.update_many.call_args.kwargs['criteria'] == {
            PORT_SECTION_INDEX_KEY: {'$exists': False}
        }

    def test_the_default_position_is_what_is_written(self) -> None:
        """The same value CmdbType.from_data falls back to, so the two cannot drift apart."""
        updater = build_stubbed_updater(Update20260918)

        updater.start_update()

        assert updater.types_manager.update_many.call_args.kwargs['update'] == {
            PORT_SECTION_INDEX_KEY: DEFAULT_PORT_SECTION_INDEX
        }

    def test_the_objects_are_not_touched(self) -> None:
        """The key is type-level only - a CmdbObject has no ports section to place."""
        updater = build_stubbed_updater(Update20260918)

        updater.start_update()

        updater.types_manager.update_many.assert_called_once()
        updater.objects_manager.update_many.assert_not_called()


class TestTheVersionBump:
    """The version is written after the work, or not at all."""

    def test_the_version_is_bumped_after_the_backfill(self) -> None:
        """On success, with this migration's own registered version."""
        updater = build_stubbed_updater(Update20260918, type_modified=5)

        updater.start_update()

        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_a_failure_leaves_the_version_alone(self) -> None:
        """A version recorded over a failed backfill would never be revisited by the runner."""
        updater = build_stubbed_updater(Update20260918)
        updater.types_manager.update_many.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()

    def test_the_original_error_is_kept_as_the_cause(self) -> None:
        """The UpdaterException wrapper must not swallow what actually failed."""
        updater = build_stubbed_updater(Update20260918)
        failure = RuntimeError('boom')
        updater.types_manager.update_many.side_effect = failure

        with pytest.raises(UpdaterException) as raised:
            updater.start_update()

        assert raised.value.__cause__ is failure


class TestMetadata:
    """The two values the runner reads before deciding to run anything."""

    def test_creation_date_is_the_registered_version(self) -> None:
        """It must equal the version registered in DatabaseUpdater.__UPDATE_VERSIONS__."""
        assert build_stubbed_updater(Update20260918).creation_date() == CREATION_DATE
        assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__

    def test_the_description_names_the_key_it_backfills(self) -> None:
        """It is user-facing - the runner prints it per migration."""
        assert PORT_SECTION_INDEX_KEY in build_stubbed_updater(Update20260918).description()

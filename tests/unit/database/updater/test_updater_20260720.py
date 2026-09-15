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
Unit tests for cmdb.database.updater.versions.updater_20260720

The migration pulls the retired 'base.framework.type.clean' right name out of every CmdbUserGroup.
Its behaviour against real collections - the pull, the untouched group, the version bump and the
double run - is tests/integration/database/test_integration_updater_20260720.py; what could not be
reached from there is the failure tail, so that is what this module owns:

  - the wrapper keeps the original error as ``__cause__`` **and** as its own argument, so a caller
    reading ``args[0]`` gets the error rather than a string of it
  - a failed pull leaves the version alone, which is what makes the migration repeat on the next start

The single ``$pull`` is asserted here too, because it is the one thing that makes a re-run a no-op:
a broader update would rewrite groups that never held the right
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so update_many_raw carries call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions.updater_20260720 import REMOVED_RIGHT, Update20260720
from cmdb.errors.updater import UpdaterException
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20260720
DATABASE_NAME: str = 'cmdb-unit'


def _build_stubbed_updater() -> Any:
    """
    Builds the updater with a stubbed database manager, bypassing the base class's wiring

    ``BaseDatabaseUpdate.__init__`` reads the config and opens a MongoDatabaseManager, so the instance
    is created through ``__new__`` and given exactly the three attributes this migration touches.

    Returns:
        Any: The updater, with a stubbed manager, database name and version bump
    """
    updater = Update20260720.__new__(Update20260720)
    updater.dbm = MagicMock()
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


class TestThePullIsTheMigration:
    """One narrow update over the groups that still carry the right name."""

    def test_only_groups_still_holding_the_right_are_matched(self) -> None:
        """
        Which is the whole of the re-run safety

        Group rights are stored as name strings, so the filter and the ``$pull`` name the same value:
        anything broader would rewrite groups that never held it.
        """
        updater = _build_stubbed_updater()

        updater.start_update()

        call = updater.dbm.update_many_raw.call_args.kwargs

        assert call['collection'] == CmdbUserGroup.COLLECTION
        assert call['db_name'] == DATABASE_NAME
        assert call['filter_query'] == {'rights': REMOVED_RIGHT}
        assert call['update'] == {'$pull': {'rights': REMOVED_RIGHT}}

    def test_the_version_is_bumped_after_the_pull(self) -> None:
        """With the updater's own registered version, once the work is done."""
        updater = _build_stubbed_updater()

        updater.start_update()

        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


class TestTheFailureTail:
    """A failed pull must be reported in full and must not be recorded as done."""

    def test_a_failure_is_wrapped_as_an_updater_exception(self) -> None:
        """The runner handles UpdaterException; anything else escapes the update pipeline."""
        updater = _build_stubbed_updater()
        updater.dbm.update_many_raw.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

    def test_the_original_error_survives_the_wrapper(self) -> None:
        """
        Both as the cause and as the wrapper's own argument

        The wrapper used to be built from ``str(err)``, which reduced a pymongo error to its message;
        it now carries the error itself, so ``args[0]`` is inspectable while ``str()`` still reads the
        same.
        """
        updater = _build_stubbed_updater()
        failure = RuntimeError('boom')
        updater.dbm.update_many_raw.side_effect = failure

        with pytest.raises(UpdaterException) as raised:
            updater.start_update()

        assert raised.value.__cause__ is failure
        assert raised.value.args[0] is failure
        assert str(raised.value) == 'boom'

    def test_a_failure_leaves_the_version_alone(self) -> None:
        """So the migration repeats on the next start instead of being recorded as complete."""
        updater = _build_stubbed_updater()
        updater.dbm.update_many_raw.side_effect = RuntimeError('boom')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()


class TestMetadata:
    """The two values the runner reads before deciding to run anything."""

    def test_creation_date_is_the_registered_version(self) -> None:
        """It must equal the version registered in DatabaseUpdater.__UPDATE_VERSIONS__."""
        assert _build_stubbed_updater().creation_date() == CREATION_DATE

    def test_the_description_names_the_removed_right(self) -> None:
        """It is user-facing - the runner prints it per migration."""
        assert REMOVED_RIGHT in _build_stubbed_updater().description()

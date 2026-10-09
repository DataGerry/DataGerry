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
Unit tests for cmdb.database.updater.versions.updater_20261004

The migration stores the 'with_port_connections' toggle's default on every CI Explorer profile lacking it. Its run
against a real collection - a stored toggle left alone, the other toggles untouched, the double run - is its own
integration test; this module owns the shape of the write and the failure tail
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so update_many_raw carries call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.updater.versions.updater_20261004 import TOGGLE, Update20261004
from cmdb.errors.updater import UpdaterException
from cmdb.models.ci_explorer_model import CiExplorerProfileKey, CmdbCiExplorerProfile
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261004
DATABASE_NAME: str = 'cmdb-unit'


def _build_stubbed_updater() -> Any:
    """The updater with a stubbed database manager, bypassing the base class's wiring."""
    updater = Update20261004.__new__(Update20261004)
    updater.dbm = MagicMock()
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater

# ---------------------------------------------------- start_update -------------------------------------------------- #

def test_sets_the_true_default_only_where_the_toggle_is_missing() -> None:
    """One bulk update on the profiles, selecting only the documents without the key"""
    updater = _build_stubbed_updater()

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.update_many_raw.call_args.kwargs
    assert kwargs == {
        'collection': CmdbCiExplorerProfile.COLLECTION,
        'db_name': DATABASE_NAME,
        'filter_query': {CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value: {'$exists': False}},
        'update': {'$set': {CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value: True}},
    }
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_the_toggle_is_the_port_connections_key() -> None:
    """Not one of the other two toggles"""
    assert TOGGLE == CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value


def test_a_failed_write_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The wrapper carries the exception (args[0] and __cause__); the version is not bumped"""
    updater = _build_stubbed_updater()
    failure = RuntimeError('down')
    updater.dbm.update_many_raw.side_effect = failure

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.args[0] is failure
    assert exc_info.value.__cause__ is failure
    updater.increase_updater_version.assert_not_called()


def test_creation_date_and_description() -> None:
    """The version is the module's date, it is registered, and the description names the toggle"""
    updater = Update20261004.__new__(Update20261004)

    assert updater.creation_date() == CREATION_DATE
    assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__
    assert updater.description() == "Adds the 'with_port_connections' toggle to every CiExplorerProfile that lacks it"

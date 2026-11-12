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
Unit tests for cmdb.database.updater.base_database_update

Verifies the abstract-method contract (the methods raise NotImplementedError when not overridden)
and that increase_updater_version persists the version via the settings manager. Instances are
created with __new__ so the real __init__ (domain manager construction) is skipped. The __init__ tests patch the
domain managers: an update runs on the caller's database manager, refuses to start without one, and falls back to
that manager's default database only for a falsy name.
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database.updater import base_database_update as module
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate, MISSING_DATABASE_MANAGER_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

OWN_DATABASE: str = 'cmdb-own'
MANAGER_DEFAULT_DATABASE: str = 'cmdb-default'
DOMAIN_MANAGERS: tuple[str, ...] = ('CategoriesManager', 'ObjectsManager', 'TypesManager', 'SettingsManager')


def _bare_base() -> BaseDatabaseUpdate:
    """A BaseDatabaseUpdate instance without the heavyweight __init__"""
    return BaseDatabaseUpdate.__new__(BaseDatabaseUpdate)


def test_creation_date_raises_when_not_overridden() -> None:
    """The base creation_date is a contract that subclasses must implement"""
    with pytest.raises(NotImplementedError):
        _bare_base().creation_date()


def test_description_raises_when_not_overridden() -> None:
    """The base description is a contract that subclasses must implement"""
    with pytest.raises(NotImplementedError):
        _bare_base().description()


def test_start_update_raises_when_not_overridden() -> None:
    """The base start_update is a contract that subclasses must implement"""
    with pytest.raises(NotImplementedError):
        _bare_base().start_update()


def test_increase_updater_version_writes_setting() -> None:
    """increase_updater_version persists the version under the 'updater' settings document"""
    base = _bare_base()
    base.settings_manager = MagicMock()

    base.increase_updater_version(20250619)

    base.settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20250619},
    )


def test_an_update_without_a_database_manager_is_refused() -> None:
    """It never builds a manager of its own: a second client and keep-alive nothing would close"""
    with pytest.raises(ValueError, match=MISSING_DATABASE_MANAGER_MESSAGE):
        BaseDatabaseUpdate(None, OWN_DATABASE)


def test_the_module_cannot_build_a_manager() -> None:
    """The fallback is gone with its imports: no MongoDatabaseManager is constructed here"""
    assert not hasattr(module, 'SystemConfigReader')


@pytest.mark.parametrize('db_name, expected', [
    (OWN_DATABASE, OWN_DATABASE),
    (None, MANAGER_DEFAULT_DATABASE),
    ('', MANAGER_DEFAULT_DATABASE),
], ids=['given', 'none', 'empty'])
def test_the_update_runs_on_the_callers_manager(db_name: str | None, expected: str) -> None:
    """The given manager is the one used; a falsy db_name means the manager's default database"""
    dbm = MagicMock(db_name=MANAGER_DEFAULT_DATABASE)

    with patch.multiple(module, **{name: MagicMock() for name in DOMAIN_MANAGERS}):
        update = BaseDatabaseUpdate(dbm, db_name)

    assert update.dbm is dbm
    assert update.db_name == expected

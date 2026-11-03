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
Unit tests for cmdb.database.updater.versions.updater_20261028

The migration deletes the user settings whose user does not exist. Its run against a real database is its own
integration test; this module owns the frozen literals, the read and the delete it sends, the empty-users guard, the
version bump and the failure tail
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261028 as module
from cmdb.database.updater.versions.updater_20261028 import Update20261028
from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261028
DATABASE_NAME: str = 'cmdb-unit'
STORED_USER_IDS: list[int] = [1, 4, 9]
DB_FAILURE: str = 'users unreadable'


def _updater(user_ids: list[int], deleted_count: int = 0) -> tuple[Update20261028, MagicMock]:
    """The migration over a mocked database manager storing these user ids"""
    dbm = MagicMock()
    dbm.get_distinct.return_value = user_ids
    dbm.delete_many_raw.return_value = MagicMock(deleted_count=deleted_count)
    updater = Update20261028(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.USERS_COLLECTION, CmdbUser.COLLECTION),
    (module.USER_SETTINGS_COLLECTION, CmdbUserSetting.COLLECTION),
    (module.USER_ID_FIELD, CmdbUserKey.PUBLIC_ID.value),
    (module.SETTING_USER_FIELD, UserSettingKey.USER_ID.value),
], ids=['users', 'settings', 'user-id', 'setting-user'])
def test_the_frozen_literals_still_match_the_models(frozen: str, live: str) -> None:
    """The literals were frozen from the models' own"""
    assert frozen == live


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater(STORED_USER_IDS)

    assert updater.creation_date() == CREATION_DATE
    assert 'user does not exist' in updater.description()


def test_the_users_are_read_once_and_every_other_owner_deleted() -> None:
    """One distinct read of the user ids, one delete of the settings naming none of them"""
    updater, dbm = _updater(STORED_USER_IDS, deleted_count=2)

    updater.start_update()

    dbm.get_distinct.assert_called_once_with(module.USERS_COLLECTION, DATABASE_NAME, module.USER_ID_FIELD, {})
    dbm.delete_many_raw.assert_called_once_with(
        module.USER_SETTINGS_COLLECTION, DATABASE_NAME, {module.SETTING_USER_FIELD: {'$nin': STORED_USER_IDS}},
    )
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_no_stored_user_deletes_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """`$nin: []` would match every setting - a database without users is damaged, not ownerless"""
    updater, dbm = _updater([])

    updater.start_update()

    dbm.delete_many_raw.assert_not_called()
    assert 'no user setting was deleted' in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failure_is_raised_as_the_updater_error_carrying_it() -> None:
    """The exception itself, so a caller can see which error it was"""
    updater, dbm = _updater(STORED_USER_IDS)
    failure = RuntimeError(DB_FAILURE)
    dbm.get_distinct.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()

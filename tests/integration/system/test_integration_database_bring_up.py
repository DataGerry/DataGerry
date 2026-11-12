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
Integration tests for how a database is brought up to date, and how a cloud tenant is set up at login, against MongoDB

* The bring-up decides by the stamp and the data, never by whether the database exists: a new database and one whose
  first setup stopped before the stamp are stamped; data without a stamp is migrated; a current stamp needs nothing
* The replay probe: a database the validator builds is at the current schema - every registered migration, run from
  the baseline against it, changes nothing but the stamp (documents and indexes). It is what makes stamping such a
  database correct, and a migration that is not a no-op on a freshly built database fails it
* The tenant setup at login runs once under the tenant's setup lock, however many logins arrive together, and a lock
  that stays held is refused with the setup not run

Each test works on a throwaway tenant database of its own, dropped afterwards
"""
import os
import threading
import time
from dataclasses import replace
from typing import Any, Iterator
from unittest.mock import patch

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import BASELINE_UPDATER_VERSION
from cmdb.database.database_services import DatabaseUpdater, bring_database_up_to_date
from cmdb.database.database_services.database_services_constants import UpdateAction, UpdaterSetting
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
from cmdb.interface import cloud_user_helper
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.manager.system_manager.settings_section_lock import acquire_section_lock, release_section_lock
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

TENANT: str = f'itest_bring_up_{os.getpid()}'
LOGINS: int = 4
SLOW_SETUP_SECONDS: float = 0.3
HOLDER: str = 'holder@x.io'
LOGIN_USER: str = 'login@x.io'
LEGACY_TYPE_ID: int = 1


@pytest.fixture(name='tenant')
def fixture_tenant(database_manager: MongoDatabaseManager) -> Iterator[str]:
    """A tenant database that does not exist yet; dropped afterwards"""
    database_manager.connector.client.drop_database(TENANT)

    yield TENANT

    database_manager.connector.client.drop_database(TENANT)


def _stamp(dbm: MongoDatabaseManager, db_name: str) -> int | None:
    """The stored stamp"""
    return DatabaseUpdater(dbm, db_name).read_stored_update_version()


def _remove_stamp(dbm: MongoDatabaseManager, db_name: str) -> None:
    """What a first setup that stopped after the validation leaves: the database, without a stamp"""
    dbm.get_collection(SettingsManager.COLLECTION, db_name).delete_one({'_id': UpdaterSetting.SECTION})


def _highest(dbm: MongoDatabaseManager, db_name: str) -> int:
    """The newest registered migration"""
    return DatabaseUpdater(dbm, db_name).get_highest_update_version()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             bring_database_up_to_date                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_new_database_is_stamped_at_the_newest_migration(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """Built at the current schema - nothing replayed"""
    with patch.object(DatabaseUpdater, 'run_updates') as run_updates:
        assert bring_database_up_to_date(database_manager, tenant) == UpdateAction.STAMP

    run_updates.assert_not_called()
    assert _stamp(database_manager, tenant) == _highest(database_manager, tenant)


def test_a_setup_that_stopped_before_the_stamp_is_stamped_not_replayed(
        database_manager: MongoDatabaseManager, tenant: str) -> None:
    """The database exists, it carries no stamp and no data: stamped on the next run"""
    bring_database_up_to_date(database_manager, tenant)
    _remove_stamp(database_manager, tenant)

    assert database_manager.check_database_exists(tenant)

    with patch.object(DatabaseUpdater, 'run_updates') as run_updates:
        assert bring_database_up_to_date(database_manager, tenant) == UpdateAction.STAMP

    run_updates.assert_not_called()
    assert _stamp(database_manager, tenant) == _highest(database_manager, tenant)


def test_data_without_a_stamp_is_migrated(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """A database from before the updater: its types may need every migration"""
    bring_database_up_to_date(database_manager, tenant)
    _remove_stamp(database_manager, tenant)
    database_manager.get_collection(CmdbType.COLLECTION, tenant).insert_one({'public_id': LEGACY_TYPE_ID})

    with patch.object(DatabaseUpdater, 'run_updates') as run_updates:
        assert bring_database_up_to_date(database_manager, tenant) == UpdateAction.MIGRATE

    run_updates.assert_called_once_with()


def test_a_current_database_is_left_alone(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """The second run validates and does nothing else"""
    bring_database_up_to_date(database_manager, tenant)

    with patch.object(DatabaseUpdater, 'run_updates') as run_updates, \
         patch.object(DatabaseUpdater, 'set_update_version') as set_version:
        assert bring_database_up_to_date(database_manager, tenant) == UpdateAction.NONE

    run_updates.assert_not_called()
    set_version.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   replay probe                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _snapshot(dbm: MongoDatabaseManager, db_name: str) -> dict[str, Any]:
    """Every collection's documents and index definitions - the updater stamp left out"""
    database = dbm.connector.client[db_name]
    snapshot: dict[str, Any] = {}

    for name in sorted(database.list_collection_names()):
        collection = database[name]
        documents = [doc for doc in collection.find({}, sort=[('_id', 1)])
                     if not (name == SettingsManager.COLLECTION and doc['_id'] == UpdaterSetting.SECTION)]
        indexes = {index_name: {key: value for key, value in spec.items() if key != 'v'}
                   for index_name, spec in collection.index_information().items()}
        snapshot[name] = (documents, indexes)

    return snapshot


def test_every_migration_is_a_no_op_on_a_freshly_built_database(
        database_manager: MongoDatabaseManager, tenant: str) -> None:
    """Replayed from the baseline, the history changes the stamp only - so stamping a new database loses nothing"""
    bring_database_up_to_date(database_manager, tenant)
    before: dict[str, Any] = _snapshot(database_manager, tenant)
    updater = DatabaseUpdater(database_manager, tenant)
    updater.set_update_version(BASELINE_UPDATER_VERSION)

    updater.run_updates()

    assert _snapshot(database_manager, tenant) == before
    assert _stamp(database_manager, tenant) == _highest(database_manager, tenant)


# -------------------------------------------------------------------------------------------------------------------- #
#                                         ensure_tenant_database (cloud login)                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def _app(dbm: MongoDatabaseManager) -> Flask:
    """A cloud app context carrying the suite's database manager"""
    app = Flask(__name__)
    app.database_manager = dbm
    app.cloud_mode = True
    app.local_mode = False

    return app


def test_logins_arriving_together_set_the_tenant_up_once(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """The first holds the setup lock; the others wait for it and find the stamp"""
    real_bring_up = cloud_user_helper.bring_database_up_to_date
    setups: list[str] = []
    errors: list[BaseException] = []
    app = _app(database_manager)

    def _slow_bring_up(dbm: MongoDatabaseManager, db_name: str) -> UpdateAction:
        setups.append(db_name)
        time.sleep(SLOW_SETUP_SECONDS)
        return real_bring_up(dbm, db_name)

    def _login(index: int) -> None:
        try:
            with app.app_context():
                cloud_user_helper.ensure_tenant_database(tenant, f'{index}@x.io')
        except BaseException as err:  # pylint: disable=broad-exception-caught
            errors.append(err)

    with patch.object(cloud_user_helper, 'bring_database_up_to_date', side_effect=_slow_bring_up):
        threads = [threading.Thread(target=_login, args=(index,)) for index in range(LOGINS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not errors
    assert setups == [tenant]
    assert _stamp(database_manager, tenant) == _highest(database_manager, tenant)


def test_a_stamped_tenant_is_not_set_up_again(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """One read - no lock, no validation"""
    bring_database_up_to_date(database_manager, tenant)

    with _app(database_manager).app_context(), \
         patch.object(cloud_user_helper, 'bring_database_up_to_date') as bring_up, \
         patch.object(cloud_user_helper, 'settings_section_lock') as lock:
        cloud_user_helper.ensure_tenant_database(tenant, LOGIN_USER)

    bring_up.assert_not_called()
    lock.assert_not_called()


def test_a_setup_lock_held_elsewhere_is_refused_and_nothing_is_set_up(
        database_manager: MongoDatabaseManager, tenant: str) -> None:
    """Another login holds it at every attempt: the error reaches the caller, the tenant stays unstamped"""
    settings_manager = SettingsManager(database_manager, tenant)
    token: str = acquire_section_lock(settings_manager, cloud_user_helper.TENANT_SETUP_LOCK, HOLDER)

    try:
        with _app(database_manager).app_context(), \
             patch.object(cloud_user_helper, 'TENANT_SETUP_LOCK',
                          replace(cloud_user_helper.TENANT_SETUP_LOCK, attempts=1)), \
             pytest.raises(SettingsSectionLockHeldError):
            cloud_user_helper.ensure_tenant_database(tenant, LOGIN_USER)
    finally:
        release_section_lock(settings_manager, cloud_user_helper.TENANT_SETUP_LOCK, token)

    assert _stamp(database_manager, tenant) is None


def test_a_half_set_up_tenant_is_finished_at_login(database_manager: MongoDatabaseManager, tenant: str) -> None:
    """The database exists without a stamp: set up at the next login, not served half-built"""
    bring_database_up_to_date(database_manager, tenant)
    _remove_stamp(database_manager, tenant)

    with _app(database_manager).app_context():
        cloud_user_helper.ensure_tenant_database(tenant, LOGIN_USER)

    assert _stamp(database_manager, tenant) == _highest(database_manager, tenant)

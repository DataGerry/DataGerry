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
Seeds and reads the configuration lock the way a running import or reset leaves it in a database

``hold_configuration_lock`` stores the lock section as another request holding it would - its own holder token, the
time it was taken - so a test can play the second request without racing a first one
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_LOCK_SECTION,
    CONFIGURATION_LOCK_TTL_SECONDS,
    ConfigurationLockKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

#: The holder token of the other request
OTHER_HOLDER: str = 'another-request'
#: public_id of the user the other request runs for
OTHER_USER_ID: int = 93001
#: An age past the TTL - a lock its holder can no longer be running
EXPIRED_AGE: timedelta = timedelta(seconds=CONFIGURATION_LOCK_TTL_SECONDS + 60)


def hold_configuration_lock(database_manager: MongoDatabaseManager, database: str,
                            age: timedelta = timedelta(0)) -> dict[str, Any]:
    """
    Stores the configuration lock as held by another request, taken ``age`` ago

    Args:
        database_manager (MongoDatabaseManager): The test's database manager
        database (str): The database whose configuration is locked
        age (timedelta): How long ago the lock was taken. Defaults to just now

    Returns:
        dict[str, Any]: The stored lock section
    """
    lock: dict[str, Any] = {
        SETTINGS_SECTION_ID_KEY: CONFIGURATION_LOCK_SECTION,
        ConfigurationLockKey.HOLDER.value: OTHER_HOLDER,
        ConfigurationLockKey.ACQUIRED_AT.value: datetime.now(timezone.utc) - age,
        ConfigurationLockKey.USER_ID.value: OTHER_USER_ID,
    }
    database_manager.get_collection(SettingsManager.COLLECTION, database).insert_one(dict(lock))

    return lock


def stored_configuration_lock(database_manager: MongoDatabaseManager, database: str) -> dict[str, Any] | None:
    """
    The configuration lock as the database holds it

    Args:
        database_manager (MongoDatabaseManager): The test's database manager
        database (str): The database to read

    Returns:
        dict[str, Any] | None: The lock section, None when nobody holds it
    """
    return database_manager.get_collection(SettingsManager.COLLECTION, database).find_one(
        {SETTINGS_SECTION_ID_KEY: CONFIGURATION_LOCK_SECTION},
    )

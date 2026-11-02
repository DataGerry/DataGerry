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
Database update 20261028: user settings that belong to no user are deleted

A user's settings are stored by the user's public_id, and until this version a settings write did not check that the
user exists. User ids come from a counter that only moves up, so the next one is predictable: a setting written for
an id no user has yet became the next created user's from its first login. The writes refuse such a user now; this
update deletes the settings already stored for one - including those a user delete's best-effort cascade left behind.

A database whose users collection is empty while settings are stored is damaged, not a database of settings without
owners: the update then deletes nothing, rather than every setting.

Re-run safe: a second run finds no setting without its user and deletes nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
USERS_COLLECTION: str = 'management.users'
USER_SETTINGS_COLLECTION: str = 'management.users.settings'
USER_ID_FIELD: str = 'public_id'
SETTING_USER_FIELD: str = 'user_id'

# ---------------------------------------------- Update20261028 - CLASS ---------------------------------------------- #

class Update20261028(BaseDatabaseUpdate):
    """
    Deletes the user settings whose user does not exist

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261028


    def description(self) -> str:
        return "Deletes the user settings whose user does not exist"


    def start_update(self) -> None:
        """
        Reads the stored users' ids once, deletes every setting naming another id, then bumps the version

        Raises:
            UpdaterException: If the read or the delete fails
        """
        try:
            user_ids: list[Any] = self.dbm.get_distinct(USERS_COLLECTION, self.db_name, USER_ID_FIELD, {})

            if user_ids:
                deleted: int = self.dbm.delete_many_raw(
                    USER_SETTINGS_COLLECTION, self.db_name, {SETTING_USER_FIELD: {'$nin': user_ids}},
                ).deleted_count

                if deleted:
                    LOGGER.info("[updater_20261028] Deleted %s user settings whose user does not exist", deleted)
            else:
                LOGGER.warning("[updater_20261028] No users are stored, so no user setting was deleted")

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

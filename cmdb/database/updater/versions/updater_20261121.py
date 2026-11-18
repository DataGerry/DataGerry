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
Database update 20261121: a user's one group becomes a list of groups

A CmdbUser may be a member of several user groups. Every stored user carrying the single ``group_id`` gets
``group_ids: [group_id]`` and loses ``group_id``, in one pipeline update. A user without a usable ``group_id`` (missing,
null or 0 - which the model always read as the default group) gets the default group, so every user carries a list.
A user carrying both keys keeps its ``group_ids``; only ``group_id`` is removed.

Re-run safe: the filter selects only users still carrying ``group_id`` or carrying no ``group_ids``, so a second run
finds none
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
USERS: str = 'management.users'
GROUP_ID: str = 'group_id'
GROUP_IDS: str = 'group_ids'
DEFAULT_GROUP: int = 2

# Users still carrying the single group, or carrying no group key at all
LEGACY_USERS: dict[str, Any] = {'$or': [{GROUP_ID: {'$exists': True}}, {GROUP_IDS: {'$exists': False}}]}

# group_ids = the stored list when there is one, else [group_id], else [the default group]; group_id removed.
# '$ifNull' covers a missing and a null value, '$cond' a 0 - all three read as the default group before
CONVERT_PIPELINE: list[dict[str, Any]] = [
    {
        '$set': {
            GROUP_IDS: {
                '$ifNull': [
                    f'${GROUP_IDS}',
                    [{'$cond': [{'$ifNull': [f'${GROUP_ID}', False]}, f'${GROUP_ID}', DEFAULT_GROUP]}],
                ],
            },
        },
    },
    {'$unset': GROUP_ID},
]

# ---------------------------------------------- Update20261121 - CLASS ---------------------------------------------- #

class Update20261121(BaseDatabaseUpdate):
    """
    Turns every user's ``group_id`` into ``group_ids``

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261121


    def description(self) -> str:
        return "Turns the one group of every user into a list of groups"


    def start_update(self) -> None:
        """
        Converts every user still carrying ``group_id``, then bumps the version

        Raises:
            UpdaterException: If the update or the version write fails
        """
        try:
            result = self.dbm.get_collection(USERS, self.db_name).update_many(LEGACY_USERS, CONVERT_PIPELINE)

            if result.modified_count:
                LOGGER.info("[updater_20261121] Converted the group of %s user(s) into a list", result.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

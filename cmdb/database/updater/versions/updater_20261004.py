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
Database update 20261004: backfill 'with_port_connections' on CI-Explorer profiles

A profile gained its third edge-source toggle, ``with_port_connections``. A stored profile that lacks
it already READS as the default (true) - the model fills a missing toggle in - so this update changes
nothing a client sees; it stores the key, so every profile document carries the same three toggles and
a query on the field finds them all.

Only a profile without the key is written, and only the key is set: a profile's other two toggles keep
whatever they hold, even where it differs from the new defaults. Idempotent by construction - a second
run selects nothing
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.ci_explorer_model import CiExplorerProfileKey, CmdbCiExplorerProfile, DEFAULT_PROFILE_SCOPE

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TOGGLE: str = CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261004 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261004(BaseDatabaseUpdate):
    """
    Backfills the 'with_port_connections' toggle (its default, true) onto every CI-Explorer profile lacking it

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261004


    def description(self) -> str:
        return "Adds the 'with_port_connections' toggle to every CiExplorerProfile that lacks it"


    def start_update(self) -> None:
        """
        Sets the toggle's default on every profile without it, in one bulk update, then bumps the version

        Raises:
            UpdaterException: If the update failed
        """
        try:
            self.dbm.update_many_raw(
                collection=CmdbCiExplorerProfile.COLLECTION,
                db_name=self.db_name,
                filter_query={TOGGLE: {'$exists': False}},
                update={'$set': {TOGGLE: DEFAULT_PROFILE_SCOPE[TOGGLE]}},
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

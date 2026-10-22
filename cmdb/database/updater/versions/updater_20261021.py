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
Database update 20261021: the old DataGerry Assistant's one-time marker is deleted

The old assistant (``/special``) recorded that it had run in the ``datagerry_assistant`` section of ``settings.conf``.
The assistant is gone - the start assistant records its own decision in a section of its own - so nothing reads the
marker any more, and the configuration reset no longer deletes it. This update deletes it once.

Re-run safe: a run finds the section or not, and a second run deletes nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
SETTINGS_COLLECTION: str = 'settings.conf'
SECTION_ID_FIELD: str = '_id'
OLD_ASSISTANT_SECTION: str = 'datagerry_assistant'

# The document the update deletes
OLD_ASSISTANT_SECTION_CRITERIA: dict[str, Any] = {SECTION_ID_FIELD: OLD_ASSISTANT_SECTION}

# ---------------------------------------------- Update20261021 - CLASS ---------------------------------------------- #

class Update20261021(BaseDatabaseUpdate):
    """
    Deletes the old DataGerry Assistant's one-time marker from the settings

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261021


    def description(self) -> str:
        return "Deletes the old DataGerry Assistant's one-time marker from the settings"


    def start_update(self) -> None:
        """
        Deletes the marker section when there is one, then bumps the version

        Raises:
            UpdaterException: If the delete fails
        """
        try:
            deleted: int = self.dbm.delete(
                SETTINGS_COLLECTION, self.db_name, OLD_ASSISTANT_SECTION_CRITERIA,
            ).deleted_count

            if deleted:
                LOGGER.info("[updater_20261021] Deleted the old DataGerry Assistant's marker")

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

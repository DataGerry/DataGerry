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
Database update 20261126: a user group sync switched on without a default Type is switched off

The user group sync creates every user group's person group in its default Type (``person_sync.groups
.default_type_id``) and is switched on only with one. A ``person_sync`` section stored before - the group sync on, no
default - would let the next pass fail on the first user group without a person group. Such a section has its group
sync switched off, in one update; the mappings (the person groups' links), the user sync and everything else stay. An
administrator chooses a default and switches the group sync on again.

Re-run safe: the filter selects only a section whose group sync is on without a default, so a second run finds none
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
SETTINGS: str = 'settings.conf'
SECTION_ID: str = 'person_sync'
GROUPS_ACTIVE: str = 'groups.active'
GROUPS_DEFAULT: str = 'groups.default_type_id'

# The section whose group sync is on without a default Type (absent or null)
ON_WITHOUT_DEFAULT: dict[str, Any] = {'_id': SECTION_ID, GROUPS_ACTIVE: True, GROUPS_DEFAULT: None}
SWITCH_OFF: dict[str, Any] = {'$set': {GROUPS_ACTIVE: False}}

# ---------------------------------------------- Update20261126 - CLASS ---------------------------------------------- #

class Update20261126(BaseDatabaseUpdate):
    """
    Switches off a user group sync stored as on without a default Type

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261126


    def description(self) -> str:
        return "A user group sync switched on without a default Type is switched off"


    def start_update(self) -> None:
        """
        Switches the group sync off where it is on without a default, then bumps the version

        Raises:
            UpdaterException: If the update or the version write fails
        """
        try:
            result: Any = self.dbm.get_collection(SETTINGS, self.db_name).update_one(ON_WITHOUT_DEFAULT, SWITCH_OFF)

            if result.modified_count:
                LOGGER.info("[updater_20261126] The user group sync was on without a default Type - switched off")

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

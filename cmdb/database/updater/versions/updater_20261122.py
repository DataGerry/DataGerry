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
Database update 20261122: a person's first and last name are no longer required

The PERSON schema stops requiring ``first_name`` and ``last_name``: a user mirrored into a person by the user sync
may carry neither, and ``display_name`` - still required - always has a value. Every stored Type carrying PERSON loses
the ``required`` flag of those two fields, in one update; its other fields, and every other Type, keep theirs.

Re-run safe: the filter selects only the Types that still carry the flag on one of the two fields, so a second run
finds none
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPES: str = 'framework.types'
SPECIAL_TYPE: str = 'special_type'
PERSON: str = 'PERSON'
FIELDS: str = 'fields'
FIELD_NAME: str = 'name'
REQUIRED: str = 'required'
NAME_FIELDS: list[str] = ['first_name', 'last_name']
# The positional identifier of the array filter naming the two fields - MongoDB allows letters and digits only
FIELD_IDENTIFIER: str = 'namefield'

# The PERSON Types where one of the two fields still carries a required flag
TYPES_STILL_REQUIRING: dict[str, Any] = {
    SPECIAL_TYPE: PERSON,
    FIELDS: {'$elemMatch': {FIELD_NAME: {'$in': NAME_FIELDS}, REQUIRED: {'$exists': True}}},
}
DROP_REQUIRED: dict[str, Any] = {'$unset': {f'{FIELDS}.$[{FIELD_IDENTIFIER}].{REQUIRED}': ''}}
NAME_FIELD_FILTERS: list[dict[str, Any]] = [{f'{FIELD_IDENTIFIER}.{FIELD_NAME}': {'$in': NAME_FIELDS}}]

# ---------------------------------------------- Update20261122 - CLASS ---------------------------------------------- #

class Update20261122(BaseDatabaseUpdate):
    """
    Drops the required flag of ``first_name`` and ``last_name`` on every Type carrying PERSON

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261122


    def description(self) -> str:
        return "A person's first and last name are no longer required"


    def start_update(self) -> None:
        """
        Drops the flag on every PERSON Type still carrying it, then bumps the version

        Raises:
            UpdaterException: If the update or the version write fails
        """
        try:
            result = self.dbm.update_many_raw(TYPES, self.db_name, TYPES_STILL_REQUIRING, DROP_REQUIRED,
                                              array_filters=NAME_FIELD_FILTERS)

            if result.modified_count:
                LOGGER.info("[updater_20261122] Dropped the required names of %s person Type(s)", result.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

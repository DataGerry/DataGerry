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
Database update 20260918: backfills CmdbType.port_section_index

`port_section_index` is the companion of `uses_ports`: it says where among a CmdbType's own sections
the frontend draws the (virtual) ports section - 0 first, 1 second, and so on. Every CmdbType written
before it existed is missing the key entirely.

The model already reads an absent key as 0 (`CmdbType.from_data`), so nothing is broken without this
migration - it exists for the same reason `updater_20260901` backfilled `uses_ports`: a key that is
present on some documents and absent on others is a trap for the next query. A
`{'port_section_index': 0}` filter, or a sort on the field, does not see a document that never got
the key, and the only way to notice is to hit it.

Every CmdbType is backfilled, not only the port-bearing ones: the key is part of a CmdbType's shape,
and a type that opts into ports later must not have to acquire it first.

Idempotent by construction: the `$exists: False` filter matches nothing on a second run, and a type
that already carries a position - whichever one - is never touched
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.type_model import DEFAULT_PORT_SECTION_INDEX, TypeSchemaKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260918 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260918(BaseDatabaseUpdate):
    """
    Gives every CmdbType that predates the key its default ports section position

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20260918


    def description(self) -> str:
        return "Backfills 'port_section_index' on all Types that do not carry the key"


    def start_update(self) -> None:
        """
        Writes the default position onto every CmdbType missing the key, then bumps the version

        Raises:
            UpdaterException: If the backfill could not be applied
        """
        try:
            result = self.types_manager.update_many(
                criteria={TypeSchemaKey.PORT_SECTION_INDEX.value: {'$exists': False}},
                update={TypeSchemaKey.PORT_SECTION_INDEX.value: DEFAULT_PORT_SECTION_INDEX},
            )

            if result.modified_count:
                LOGGER.info(
                    "[Update20260918] Backfilled 'port_section_index' on %s Type(s)", result.modified_count
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

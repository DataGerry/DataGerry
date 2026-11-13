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
Database update 20261116: drop the SpecialType index that held every marker unique, and mark every stored Type
as no system Type

``framework.types`` declared ``special_type`` - unique over every Type whose marker is a non-empty string. Since
PERSON and PERSON_GROUP may be carried by any number of Types, only the singleton markers (SUPERNET, SUBNET, VLAN,
RACK, CABLE) are held unique, by the successor ``special_type_singleton``, whose partial filter lists them.

The startup index reconciliation only adds a declared index whose NAME is missing; it never drops one. The successor
therefore carries a new name and is added by the reconciliation, and this update drops the predecessor - which would
otherwise go on refusing a second PERSON or PERSON_GROUP Type.

Every stored Type also gets ``system_type: false`` - the server-owned marker of a Type the system created and depends
on, which no Type stored before this version is. Written rather than left to the readers' default, so every Type a
route answers carries the key.

Re-run safe: a second run finds no such index and drops nothing, and selects only Types without the marker. A
database that never had the index (a new install) is the same no-op
"""
from logging import Logger, getLogger

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPES_COLLECTION: str = 'framework.types'
REPLACED_INDEX: str = 'special_type'
SYSTEM_TYPE_FIELD: str = 'system_type'

# ---------------------------------------------- Update20261116 - CLASS ---------------------------------------------- #

class Update20261116(BaseDatabaseUpdate):
    """
    Drops the types collection's ``special_type`` index, replaced by ``special_type_singleton``, which holds only the
    singleton SpecialTypes unique, and writes ``system_type: false`` onto every Type without the key

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261116


    def description(self) -> str:
        return "Lets several types carry PERSON or PERSON_GROUP, and marks every type as no system type"


    def start_update(self) -> None:
        """
        Drops the replaced index of the types collection when it is present, marks every Type without the marker as
        no system Type, then bumps the version

        Raises:
            UpdaterException: If the index exists but cannot be dropped, the marker cannot be written, or the version
                cannot be written
        """
        try:
            if self.dbm.drop_index(TYPES_COLLECTION, self.db_name, REPLACED_INDEX):
                LOGGER.info("[updater_20261116] Dropped the '%s' index of %s", REPLACED_INDEX, TYPES_COLLECTION)
            else:
                LOGGER.info("[updater_20261116] No '%s' index on %s - nothing to drop", REPLACED_INDEX,
                            TYPES_COLLECTION)

            marked = self.dbm.update_many(TYPES_COLLECTION, self.db_name, {SYSTEM_TYPE_FIELD: {'$exists': False}},
                                          {SYSTEM_TYPE_FIELD: False})
            LOGGER.info("[updater_20261116] Marked %s type(s) as no system type", marked.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

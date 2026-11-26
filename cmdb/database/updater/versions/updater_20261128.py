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
Database update 20261128: every object gets its materialised scope block (``_scope``)

A scope's location and network conditions read the block - the location chain the object is placed under, the networks
and the addresses of its interface rows (phase 10). The object writes keep it current from now on; this update computes
it once for the objects stored before. It runs the live computation (``ObjectScopeBlocks.refresh``) on purpose: the
block is derived data that must equal what the writes compute, and a later change of its shape ships its own update
running it again.

Re-run safe: ``refresh`` writes only a block that differs from the computed one, so a second run - or a run after one
stopped part-way - writes only the objects still missing theirs. A database without objects gets only the version stamp
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
OBJECTS: str = 'framework.objects'
PUBLIC_ID: str = 'public_id'
MONGO_ID: str = '_id'
# Objects handed to one refresh
BATCH_SIZE: int = 1000


# --------------------------------------------- Update20261128 - CLASS ---------------------------------------------- #

class Update20261128(BaseDatabaseUpdate):
    """
    Computes the materialised scope block of every stored object

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261128


    def description(self) -> str:
        return "Every object gets its materialised scope block"


    def start_update(self) -> None:
        """
        Refreshes the block of every object, batch by batch, then bumps the version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            blocks: ObjectScopeBlocks = ObjectScopeBlocks(self.objects_manager)
            cursor: Any = self.dbm.find(OBJECTS, self.db_name, {}, projection={MONGO_ID: 0, PUBLIC_ID: 1})
            batch: list[int] = []
            written: int = 0

            for document in cursor:
                batch.append(document[PUBLIC_ID])

                if len(batch) >= BATCH_SIZE:
                    written += blocks.refresh(batch)
                    batch = []

            written += blocks.refresh(batch)
            LOGGER.info("[updater_20261128] %d scope blocks written", written)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err

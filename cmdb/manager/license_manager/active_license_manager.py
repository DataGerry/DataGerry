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
Implementation of ActiveLicenseManager (license feature part P13, persistence)

Stores the single active license for the install in the `license.activeLicense` collection. Only
the raw license blob is persisted (plus the activation timestamp); the entitlement is re-derived by
verifying the blob on read, so a stored license that later expires is reflected without rewriting
it. The collection holds at most one document, addressed by a fixed id
"""
from logging import Logger, getLogger
import time
from typing import Optional, Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Fixed _id of the single active-license document
ACTIVE_LICENSE_ID: str = 'active'

# Document keys of the active-license document
LICENSE_BLOB_KEY: str = 'blob'
ACTIVATED_AT_KEY: str = 'activated_at'

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ActiveLicenseManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class ActiveLicenseManager(BaseManager):
    """
    Database manager for the single active license blob

    Extends: BaseManager
    """
    COLLECTION: str = 'license.activeLicense'

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ActiveLicenseManager

        Args:
            dbm (MongoDatabaseManager): The database interaction manager
            database (str | None): Target tenant database name (cloud mode); None on-premise
        """
        super().__init__(self.COLLECTION, dbm, database)


    def set_active_license(self, blob: str) -> None:
        """
        Stores (replacing any existing) the active license blob

        Args:
            blob (str): The Base64 license blob to activate
        """
        document: dict[str, Any] = {
            LICENSE_BLOB_KEY: blob,
            ACTIVATED_AT_KEY: int(time.time()),
        }

        self.upsert({'_id': ACTIVE_LICENSE_ID}, document)


    def get_active_license_blob(self) -> Optional[str]:
        """
        Retrieves the stored active license blob

        Returns:
            Optional[str]: The stored blob, or None if no license is active
        """
        document = self.get_one_by({'_id': ACTIVE_LICENSE_ID})

        return document.get(LICENSE_BLOB_KEY) if document else None


    def clear_active_license(self) -> bool:
        """
        Removes the active license (degrading the install back to the free tier)

        Returns:
            bool: True if a license was removed, False if none was active
        """
        return self.delete({'_id': ACTIVE_LICENSE_ID})

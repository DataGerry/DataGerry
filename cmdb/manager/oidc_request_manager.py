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
Implementation of OidcRequestManager

Stores short-lived OIDC authorization request state (state/nonce/spa_origin) so the
callback can verify the request (CSRF/replay protection) across multiple workers.
"""
from logging import Logger, getLogger
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

OIDC_REQUEST_TTL_SECONDS = 600

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OidcRequestManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class OidcRequestManager(BaseManager):
    """
    Manages the transient 'auth.oidc_requests' collection used during the OIDC login flow

    Extends: BaseManager
    """
    COLLECTION = 'auth.oidc_requests'

    def __init__(self, dbm: MongoDatabaseManager, database_name: str = None):
        """
        Set the database connection for the OidcRequestManager and ensure the TTL index

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database_name (str): Name of the database. Only relevant in CLOUD_MODE
        """
        super().__init__(OidcRequestManager.COLLECTION, dbm, database_name)
        self._ensure_ttl_index()


    def _ensure_ttl_index(self) -> None:
        """
        Ensure the TTL index (garbage collection for abandoned logins) and the unique
        index on 'state'. Idempotent - pymongo no-ops on an identical existing index.
        """
        try:
            collection = self.dbm.get_collection(self.collection, self.db_name)
            collection.create_index(
                [('created_at', 1)], name='created_at_ttl', expireAfterSeconds=OIDC_REQUEST_TTL_SECONDS
            )
            collection.create_index([('state', 1)], name='state_unique', unique=True)
        except Exception as err:
            LOGGER.warning("[OidcRequestManager] Could not ensure indexes: %s", err)


    def store(self, state: str, nonce: str, spa_origin: str) -> None:
        """
        Persist an OIDC authorization request

        Uses a raw insert_one (not BaseManager.insert) to avoid public_id counter injection.
        """
        collection = self.dbm.get_collection(self.collection, self.db_name)
        collection.insert_one({
            'state': state,
            'nonce': nonce,
            'spa_origin': spa_origin,
            'created_at': datetime.now(timezone.utc),
        })


    def consume(self, state: str) -> dict | None:
        """
        Atomically fetch and delete the request matching the given state (single use)

        Returns:
            dict | None: The stored request document, or None if not found (replay/expired)
        """
        collection = self.dbm.get_collection(self.collection, self.db_name)
        return collection.find_one_and_delete({'state': state})

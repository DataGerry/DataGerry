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
Implementation of LicenseActivationRequestsManager (license feature part P9, persistence)

Persists offline activation requests in the `license.activationRequestRecords` collection (keyed by
an integer public_id). It issues a fresh request - superseding any still-pending one so only the
newest request is PENDING - looks one up by id or by hmac (the latter is the P11 findByHmac binding
step), and evaluates lazy TTL expiry against a storage-only `created_at`. The stored document is the
activation request's full wire dict (id, hmac, ttl, status + machine fields) plus `created_at`; the
downloadable request file is the trimmed 6-field projection (no ttl / status / created_at). Expiry
runs without a scheduler: superseded at create time, and flipped on read for a lone stale request
"""
from logging import Logger, getLogger
import time
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager

from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.activation_lifecycle import (
    DEFAULT_TTL_SECONDS,
    build_activation_request,
    is_request_expired,
    new_request_id,
)
from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Storage-only field holding the epoch-seconds creation time (drives lazy TTL; not part of the blob)
ACTIVATION_CREATED_AT_KEY: str = 'created_at'

# -------------------------------------------------------------------------------------------------------------------- #
#                                      LicenseActivationRequestsManager - CLASS                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class LicenseActivationRequestsManager(BaseManager):
    """
    Database manager for offline license activation requests

    Extends: BaseManager
    """
    COLLECTION: str = 'license.activationRequestRecords'

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the LicenseActivationRequestsManager

        Args:
            dbm (MongoDatabaseManager): The database interaction manager
            database (str | None): Target tenant database name (cloud mode); None on-premise
        """
        super().__init__(self.COLLECTION, dbm, database)


    def create_activation_request(
        self,
        fingerprint: dict[str, str],
        ttl: int = DEFAULT_TTL_SECONDS,
    ) -> LicenseActivationRequest:
        """
        Builds, persists and returns a fresh PENDING activation request

        Any still-pending requests are first superseded (bulk-marked EXPIRED) so at most one PENDING
        request is ever live. The new request is then bound to the fingerprint (HMAC) and stored with
        an integer public_id and a storage-only creation timestamp for lazy TTL

        Args:
            fingerprint (dict[str, str]): The machine fingerprint (get_machine_fingerprint shape)
            ttl (int): Time-to-live in seconds; defaults to DEFAULT_TTL_SECONDS

        Returns:
            LicenseActivationRequest: The persisted activation request
        """
        self._supersede_pending_requests()

        request = build_activation_request(fingerprint, new_request_id(), ttl)

        document = LicenseActivationRequest.to_json(request)
        document[ACTIVATION_CREATED_AT_KEY] = int(time.time())

        self.insert(document)

        return request


    def _supersede_pending_requests(self) -> None:
        """
        Marks every still-PENDING activation request as EXPIRED

        The create-time half of the no-scheduler expiry strategy: invoked before a new request is
        stored so only the newest request can be PENDING
        """
        self.update_many(
            {ActivationRequestKey.STATUS: ActivationRequestStatus.PENDING.value},
            {ActivationRequestKey.STATUS: ActivationRequestStatus.EXPIRED.value},
        )


    def get_by_request_id(self, request_id: str) -> dict[str, Any] | None:
        """
        Retrieves a stored activation request by its id

        Args:
            request_id (str): The activation request id

        Returns:
            dict[str, Any] | None: The stored document, or None if no request has that id
        """
        return self.get_one_by({ActivationRequestKey.ID: request_id})


    def get_by_hmac(self, hmac: str) -> dict[str, Any] | None:
        """
        Retrieves a stored activation request by its machine-binding HMAC (P11 findByHmac)

        Args:
            hmac (str): The machine-binding HMAC

        Returns:
            dict[str, Any] | None: The stored document, or None if no request carries that hmac
        """
        return self.get_one_by({ActivationRequestKey.HMAC: hmac})


    def delete_by_request_id(self, request_id: str) -> bool:
        """
        Deletes a stored activation request by its id

        Args:
            request_id (str): The activation request id

        Returns:
            bool: True if a document was deleted, False otherwise
        """
        return self.delete({ActivationRequestKey.ID: request_id})


    @staticmethod
    def is_document_expired(document: dict[str, Any], now: int | None = None) -> bool:
        """
        Decides whether a stored activation-request document has expired (lazy TTL)

        Args:
            document (dict[str, Any]): A stored activation-request document
            now (int | None): Epoch seconds to evaluate against; defaults to the current time

        Returns:
            bool: True once the stored creation time plus its ttl has been reached
        """
        return is_request_expired(
            document[ACTIVATION_CREATED_AT_KEY],
            document[ActivationRequestKey.TTL],
            now,
        )

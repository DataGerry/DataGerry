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
Implementation of SecurityManager
"""
import os
import base64
from logging import Logger, getLogger
import hashlib
import hmac
<<<<<<< HEAD
import json
=======
>>>>>>> origin/version-3.2

from Crypto import Random
from flask import current_app
from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SecurityManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class SecurityManager:
    """
    Handles password HMAC generation and symmetric AES key management.

    The symmetric AES key is used to key the HMAC-SHA256 used for password storage/verification;
    the key itself is resolved from the app (cloud+local dev), an environment variable (cloud), or
    the 'security' settings section (on-premise, generated on first use).
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initializes the SecurityManager with a given database manager and optional database selection

        Args:
            dbm (MongoDatabaseManager): The database manager to interact with the database
            database (str, optional): The database name to use. Defaults to None
        """
        self.settings_manager: SettingsManager = SettingsManager(dbm, database)
        self.salt: str = "cmdb"


    def generate_hmac(self, data: str) -> str:
        """
        Generates a deterministic HMAC-SHA256 of the given data, keyed with the stored symmetric AES key

        This is the password-storage primitive: the same input always maps to the same hash (keyed by
        the instance's symmetric AES key plus a fixed application salt), so a login attempt can be
        hashed and compared against the stored value.

        Backend design note: there is intentionally NO per-user salt — the salt is a single
        application-wide constant, so identical passwords hash to identical values. Changing the salt,
        the hash algorithm, or the key derivation would invalidate every already-stored password, so
        this scheme is kept stable rather than changed in place.

        Args:
            data (str): The data (e.g. a plaintext password) to hash

        Returns:
            str: The base64-encoded HMAC-SHA256 digest
        """
        generated_hash = hmac.new(
            self.get_symmetric_aes_key(),
            bytes(data + self.salt, 'utf-8'),
            hashlib.sha256
        )

        return base64.b64encode(generated_hash.digest()).decode("utf-8")


    def generate_symmetric_aes_key(self) -> UpdateResult:
        """
        Generates a new random symmetric AES key and stores it in the 'security' settings section

        Returns:
            UpdateResult: The result of the settings write operation
        """
        return self.settings_manager.write('security', {'symmetric_aes_key': Random.get_random_bytes(32)})


    def get_symmetric_aes_key(self) -> bytes:
        """
        Retrieves the symmetric AES key used for HMAC and AES operations

        Resolution order:
            - cloud + local mode: the dev key carried on the app (``current_app.symmetric_key``)
            - cloud (non-local): the base64-encoded key from the ``DG_SYMMETRIC_KEY`` env variable
            - on-premise: the key stored in the 'security' settings section, generated on first use

        Returns:
            bytes: The symmetric AES key

        Raises:
            ValueError: In cloud (non-local) mode when ``DG_SYMMETRIC_KEY`` is not set
        """
        if current_app.cloud_mode:
            if current_app.local_mode:
                return current_app.symmetric_key

            env_symmetric_key = os.getenv("DG_SYMMETRIC_KEY")

            if not env_symmetric_key:
                LOGGER.error("[get_symmetric_aes_key] No symmetric key provided via 'DG_SYMMETRIC_KEY'!")
                raise ValueError("No symmetric AES key provided via the 'DG_SYMMETRIC_KEY' environment variable")

            return base64.b64decode(env_symmetric_key)

        symmetric_key = self.settings_manager.get_value('symmetric_aes_key', 'security')

        if not symmetric_key:
            self.generate_symmetric_aes_key()
            symmetric_key = self.settings_manager.get_value('symmetric_aes_key', 'security')

        return symmetric_key

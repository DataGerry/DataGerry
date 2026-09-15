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
Implementation of KeyHolder
"""
import os
import base64
from logging import Logger, getLogger

from flask import current_app

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   KeyHolder - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class KeyHolder:
    """
    A class responsible for managing RSA public and private keys used for encryption and decryption

    This class retrieves the RSA keys from different sources depending on the environment:
    - In cloud mode, it retrieves keys from the `current_app` or environment variables
    - In local mode, it retrieves keys from the application's configuration settings
    """

    def __init__(self, dbm: MongoDatabaseManager, with_private_key: bool = True) -> None:
        """
        Initializes the KeyHolder instance, loading the RSA keys it is asked for

        Both keys are loaded by default, because a holder is normally built to SIGN. Verifying needs
        the public key alone (`TokenValidator`), and in local mode every load is a settings read of
        the same document - so a holder that will never sign asks for `with_private_key=False`
        rather than reading the private key it cannot use

        Args:
            dbm (MongoDatabaseManager): The database manager used for retrieving application settings
            with_private_key (bool): Whether to load the private key as well. Defaults to True

        Attributes:
            settings_manager (SettingsManager): Manages the settings for the application
            rsa_public (bytes): The RSA public key used for encryption
            rsa_private (bytes | None): The RSA private key used for decryption, None when it was
                not asked for
        """
        self.settings_manager: SettingsManager = SettingsManager(dbm)
        self.rsa_public: bytes = self.get_public_key()
        self.rsa_private: bytes | None = self.get_private_key() if with_private_key else None


    def get_public_key(self) -> bytes:
        """
        Retrieves the RSA public key

        The public key is retrieved from the following sources based on the environment:
        - In cloud mode, it checks the `current_app` or environment variable for the public key
        - In local mode, it fetches the public key from the application settings

        Returns:
            bytes: The RSA public key, decoded from base64 if retrieved from environment variables

        Raises:
            ValueError: In cloud (non-local) mode when 'DG_RSA_PUBLIC_KEY' is not set
        """
        if current_app.cloud_mode:
            if current_app.local_mode:
                return current_app.asymmetric_key['public']

            env_public_key = os.getenv("DG_RSA_PUBLIC_KEY")

            if not env_public_key:
                LOGGER.error("[get_public_key] No RSA public key provided via 'DG_RSA_PUBLIC_KEY'!")
                raise ValueError("No RSA public key provided via the 'DG_RSA_PUBLIC_KEY' environment variable")

            return base64.b64decode(env_public_key)

        return self.settings_manager.get_value('asymmetric_key', 'security')['public']


    def get_private_key(self) -> bytes:
        """
        Retrieves the RSA private key

        Similar to `get_public_key`, the private key is retrieved from different sources depending on the environment:
        - In cloud mode, it checks the `current_app` or environment variable for the private key
        - In local mode, it fetches the private key from the application settings

        Returns:
            bytes: The RSA private key, decoded from base64 if retrieved from environment variables

        Raises:
            ValueError: In cloud (non-local) mode when 'DG_RSA_PRIVATE_KEY' is not set
        """
        if current_app.cloud_mode:
            if current_app.local_mode:
                return current_app.asymmetric_key['private']

            env_private_key = os.getenv("DG_RSA_PRIVATE_KEY")

            if not env_private_key:
                LOGGER.error("[get_private_key] No RSA private key provided via 'DG_RSA_PRIVATE_KEY'!")
                raise ValueError("No RSA private key provided via the 'DG_RSA_PRIVATE_KEY' environment variable")

            return base64.b64decode(env_private_key)

        return self.settings_manager.get_value('asymmetric_key', 'security')['private']

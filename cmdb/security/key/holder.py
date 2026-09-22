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
from logging import Logger, getLogger
from typing import Any

from flask import current_app

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.security.key.secret_resolver import (
    ASYMMETRIC_KEY_SETTING,
    SECURITY_SECTION,
    resolve_secret,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Environment variables carrying the Base64 keypair on a hosted cloud installation, and the halves
# of the stored keypair document they correspond to
PUBLIC_KEY_ENV_VAR: str = 'DG_RSA_PUBLIC_KEY'
PRIVATE_KEY_ENV_VAR: str = 'DG_RSA_PRIVATE_KEY'
PUBLIC_HALF: str = 'public'
PRIVATE_HALF: str = 'private'

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
        self._stored_keypair: dict[str, Any] | None = None
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
        return resolve_secret(
            dev_value=lambda: current_app.asymmetric_key[PUBLIC_HALF],
            env_var=PUBLIC_KEY_ENV_VAR,
            label='RSA public key',
            stored_value=lambda: self._stored_half(PUBLIC_HALF),
        )


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
        return resolve_secret(
            dev_value=lambda: current_app.asymmetric_key[PRIVATE_HALF],
            env_var=PRIVATE_KEY_ENV_VAR,
            label='RSA private key',
            stored_value=lambda: self._stored_half(PRIVATE_HALF),
        )


    def _stored_half(self, half: str) -> bytes:
        """
        Reads one half of the stored keypair, fetching the document at most once per holder

        Both halves live in ONE settings document and a holder that signs asks for both, so an
        uncached read cost two round trips to build one holder - and `TokenGenerator` calls
        `get_private_key()` again for every token it signs, which made it three per login. The
        keypair is written once when the database is created and never rotated, so caching it for
        the lifetime of a holder cannot go stale

        Args:
            half (str): Which half to read - PUBLIC_HALF or PRIVATE_HALF

        Returns:
            bytes: The requested half of the RSA keypair
        """
        if self._stored_keypair is None:
            self._stored_keypair = self.settings_manager.get_value(ASYMMETRIC_KEY_SETTING, SECURITY_SECTION)

        return self._stored_keypair[half]

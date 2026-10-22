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
Implementation of KeyGenerator - the first-boot writer of an on-premise installation's two secrets

Run once, when startup creates the database (``CollectionValidator.init_keys``); nothing replaces either secret while
the process runs. The cloud modes take their keys from the app or the environment and never run it
"""
from logging import Logger, getLogger

from Crypto.PublicKey import RSA

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.security.key.secret_resolver import (
    ASYMMETRIC_KEY_SETTING,
    SECURITY_SECTION,
    SYMMETRIC_KEY_SETTING,
    new_symmetric_aes_key,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 KeyGenerator - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class KeyGenerator:
    """
    Generates the two secrets of an on-premise installation and stores them in the 'security' settings section

    - the **RSA keypair**, which signs (private half) and verifies (public half) every login token
      (``TokenGenerator``, ``TokenValidator``, read through ``KeyHolder``)
    - the **symmetric key** that keys the password HMAC (``SecurityManager.generate_hmac``) - called an AES key
      for its size; no AES cipher uses it

    Neither encrypts anything
    """

    def __init__(self, dbm: MongoDatabaseManager) -> None:
        """
        Initializes the KeyGenerator

        Args:
            dbm (MongoDatabaseManager): The database manager used to interact with the application's settings
        """
        self.settings_manager = SettingsManager(dbm)


    def generate_rsa_keypair(self) -> None:
        """
        Generates the 2048-bit RSA keypair that signs and verifies login tokens

        Both halves are exported as PEM and stored together under ``asymmetric_key`` in the 'security' section:
        the private half signs a token (``TokenGenerator``), the public half verifies one (``TokenValidator``)
        """
        key = RSA.generate(2048)
        private_key = key.export_key()
        public_key = key.publickey().export_key()

        asymmetric_key = {
            'private': private_key,
            'public': public_key
        }

        self.settings_manager.write(SECURITY_SECTION, {ASYMMETRIC_KEY_SETTING: asymmetric_key})


    def generate_symmetric_aes_key(self) -> None:
        """
        Generates the 256-bit symmetric key that keys the password HMAC

        The key comes from `new_symmetric_aes_key`, which `SecurityManager` also uses for its lazy
        fallback: two entry points, one definition of what the key is and where it is written
        """
        self.settings_manager.write(SECURITY_SECTION, {SYMMETRIC_KEY_SETTING: new_symmetric_aes_key()})

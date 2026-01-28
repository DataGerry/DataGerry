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
Implementation of KeyGenerator
"""
import logging
from Crypto import Random
from Crypto.PublicKey import RSA

from cmdb.database import MongoDatabaseManager

from cmdb.manager import SettingsManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 KeyGenerator - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class KeyGenerator:
    """
    A class to generate cryptographic keys, including RSA key pairs and symmetric AES keys

    This class is responsible for generating:
    - RSA key pairs (public and private keys) for asymmetric encryption
    - AES keys for symmetric encryption
    
    The generated keys are then stored in the application's settings via the `SettingsManager`
    """

    def __init__(self, dbm: MongoDatabaseManager):
        """
        Initializes the KeyGenerator

        Args:
            dbm (MongoDatabaseManager): The database manager used to interact with the application's settings
        """
        self.settings_manager = SettingsManager(dbm)


    def generate_rsa_keypair(self) -> None:
        """
        Generates an RSA key pair (private and public) for asymmetric encryption.

        The RSA key pair is 2048 bits in size and is exported in a format suitable for storage.
        The generated keys are saved in the application's settings under the 'security' section.

        The generated keys are:
        - Private key: Used for decryption or signing operations
        - Public key: Used for encryption or verification operations
        """
        key = RSA.generate(2048)
        private_key = key.export_key()
        public_key = key.publickey().export_key()

        asymmetric_key = {
            'private': private_key,
            'public': public_key
        }

        self.settings_manager.write('security', {'asymmetric_key': asymmetric_key})


    def generate_symmetric_aes_key(self) -> None:
        """
        Generates a 256-bit AES key for symmetric encryption.

        This method generates a random AES key using the `Random` module and stores it in the application's settings.
        """
        symmetric_aes_key = Random.get_random_bytes(32)

        self.settings_manager.write('security', {'symmetric_aes_key': symmetric_aes_key})

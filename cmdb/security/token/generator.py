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
Implementation of TokenGenerator
"""
from logging import Logger, getLogger
from datetime import datetime, timedelta, timezone

from joserfc import jwt
from joserfc.jwk import RSAKey

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager

from cmdb import __title__
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.key.holder import KeyHolder
from cmdb.security.token.token_constants import TokenAlgorithm
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TokenGenerator - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TokenGenerator:
    """
    A class to handle JWT token generation and related operations.

    This class is responsible for generating secure tokens with specific claims
    and expiration times. It includes methods for setting token expiration,
    and generating tokens based on a provided payload with optional additional claims.
    """
    DEFAULT_CLAIMS = {
        'iss': {
            'essential': True,
            'value': __title__
        }
    }

    def __init__(self, dbm: MongoDatabaseManager = None):
        """
        Initializes the TokenGenerator

        Args:
            dbm (MongoDatabaseManager, optional): Database manager to interact with the database
        """
        self.key_holder = KeyHolder(dbm)

        self.header = {
            'alg': TokenAlgorithm.RS512.value
        }

        #TODO: REFACTOR-FIX
        settings_manager = SettingsManager(dbm)
        self.auth_module = AuthModule(
            settings_manager.get_all_values_from_section(
                'auth',
                AuthModule.__DEFAULT_SETTINGS__
            )
        )


    def get_expire_time(self) -> datetime:
        """
        Calculates the expiration time of the token based on the configured lifetime

        Returns:
            datetime: The calculated expiration time, set to the current time plus the token lifetime
        """
        expire_time = int(self.auth_module.settings.get_token_lifetime())
        return datetime.now(timezone.utc) + timedelta(minutes=expire_time)


    def generate_token(self, payload: dict, optional_claims: dict = None) -> bytes:
        """
        Generates a JWT token using the provided payload and optional additional claims.

        This method combines default claims, token-specific claims (like `iat` and `exp`),
        and any optional claims provided to generate a signed JWT token.

        Args:
            payload (dict): The main payload to be included in the token's claims
            optional_claims (dict, optional): Additional claims to be included in the token

        Returns:
            bytes: The encoded JWT token as a byte string
        """
        optional_claims = optional_claims or {}

        token_claims = {
            'iat': int(datetime.now(timezone.utc).timestamp()),
            'exp': int(self.get_expire_time().timestamp())
        }
        payload_claims = {
            'DATAGERRY': {
                'essential': True,
                'value': payload
            }
        }
        claims = {**self.DEFAULT_CLAIMS, **token_claims, **payload_claims, **optional_claims}
        private_key = RSAKey.import_key(self.key_holder.get_private_key())
        token = jwt.encode(self.header, claims, private_key, algorithms=[TokenAlgorithm.RS512.value])

        return token.encode('utf-8')

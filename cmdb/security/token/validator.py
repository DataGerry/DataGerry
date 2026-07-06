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
Implementation of TokenValidator
"""
from logging import Logger, getLogger
import time

from authlib.jose import jwt, JsonWebToken
from authlib.jose.errors import BadSignatureError, InvalidClaimError

from cmdb.database import MongoDatabaseManager

from cmdb.security.key.holder import KeyHolder

from cmdb.errors.security import TokenValidationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TokenValidator - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TokenValidator:
    """
    Decodes and validates JSON Web Tokens (JWTs)
    """
    def __init__(self, dbm: MongoDatabaseManager):
        """
        Initializes the TokenValidator with a KeyHolder instance

        Args:
            dbm (MongoDatabaseManager): Database operations manager
        """
        self.key_holder = KeyHolder(dbm)


    def decode_token(self, token: JsonWebToken | str | dict) -> dict:
        """
        Decodes a given JWT token

        Args:
            token (JsonWebToken | str | dict): The JWT token to be decoded

        Returns:
            dict: The decoded JWT claims

        Raises:
            TokenValidationError: If the token is invalid, malformed, or has a bad signature
        """
        try:
            public_key = self.key_holder.get_public_key()
            decoded_token = jwt.decode(token, key=public_key)

            # LOGGER.debug(f"decoded_token type: {type(decoded_token)}")
            return decoded_token
        except (BadSignatureError, Exception) as err:
            raise TokenValidationError(err) from err


    def validate_token(self, token: JsonWebToken | str | dict):
        """
        Validates a given token regarding its expiration

        Params:
            token(JsonWebToken | str | dict): the given token

        Returns:
            JWTClaims: decoded token
        """
        try:
            token.validate(time.time())
        except InvalidClaimError as err:
            raise TokenValidationError(err) from err

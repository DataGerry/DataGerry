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

from joserfc import jwt
from joserfc.jwk import RSAKey
from joserfc.errors import JoseError

from cmdb.database import MongoDatabaseManager

from cmdb.security.key.holder import KeyHolder
from cmdb.security.token.token_constants import TokenAlgorithm, TokenTimeClaim

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


    def decode_token(self, token: str | bytes) -> dict:
        """
        Decodes a given JWT token and verifies its RSA signature

        The token must be signed with the algorithm whitelisted in TokenAlgorithm; any other
        algorithm is rejected before the signature is checked.

        Args:
            token (str | bytes): The encoded JWT token to be decoded

        Returns:
            dict: The decoded JWT claims

        Raises:
            TokenValidationError: If the token is invalid, malformed, or has a bad signature
        """
        try:
            public_key = RSAKey.import_key(self.key_holder.get_public_key())
            decoded_token = jwt.decode(token, public_key, algorithms=[TokenAlgorithm.RS512])

            return decoded_token.claims
        except Exception as err:
            raise TokenValidationError(err) from err


    def validate_token(self, token: dict) -> None:
        """
        Validates the decoded token claims regarding their expiration

        Only the registered time claims (TokenTimeClaim) are validated, mirroring the previous
        authlib behaviour which did not enforce a format on DataGerry's structured 'iss' and
        'DATAGERRY' claims.

        Args:
            token (dict): The decoded JWT claims returned by decode_token

        Raises:
            TokenValidationError: If a time claim is invalid or the token has expired
        """
        try:
            time_claims = {claim.value: token[claim.value] for claim in TokenTimeClaim if claim.value in token}
            claims_registry = jwt.JWTClaimsRegistry(now=int(time.time()))
            claims_registry.validate(time_claims)
        except JoseError as err:
            raise TokenValidationError(err) from err

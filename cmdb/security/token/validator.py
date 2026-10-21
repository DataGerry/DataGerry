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
Implementation of TokenValidator

Accepting a DataGerry JWT takes **two steps, and both are mandatory**:

1. `decode_token` verifies the RSA signature and the algorithm. It does **not** look at any claim -
   `joserfc.jwt.decode` never does - so an expired token decodes perfectly well here.
2. `validate_claims` enforces the registered time claims: `exp` is required, `iat` / `nbf` are
   checked when present, all with a small clock-skew tolerance.

Both run once per request, in `route_utils.parse_authorization_header` -> `_validate_bearer`, whose
result is cached for the request; the per-route decorators read the cached claims rather than
repeating either step. A caller that decodes a token itself and skips step 2 accepts expired
credentials, which is why the two are documented together here.

The two failure modes are deliberately different exceptions, because they are different HTTP answers:
a `TokenValidationError` is the caller's problem (401), a `TokenKeyMaterialError` is the server's
(500) - an unset `DG_RSA_PUBLIC_KEY` or an unreadable settings document is not a bad credential.
"""
from logging import Logger, getLogger
import time
from typing import Any

from joserfc import jwt
from joserfc.jwk import RSAKey
from joserfc.errors import JoseError

from cmdb.database import MongoDatabaseManager

from cmdb.security.key.holder import KeyHolder
from cmdb.security.token.token_constants import (
    TOKEN_TIME_CLAIM_LEEWAY,
    TokenAlgorithm,
    TokenClaim,
    TokenClaimWrapperKey,
    TokenTimeClaim,
)

from cmdb.errors.security import TokenKeyMaterialError, TokenValidationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TokenValidator - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TokenValidator:
    """
    Verifies a DataGerry JWT's signature and enforces its time claims

    Two steps, both required to accept a token - see the module docstring
    """
    def __init__(self, dbm: MongoDatabaseManager) -> None:
        """
        Initializes the TokenValidator with a KeyHolder instance

        Args:
            dbm (MongoDatabaseManager): Database operations manager
        """
        self.key_holder: KeyHolder = KeyHolder(dbm, with_private_key=False)


    def decode_token(self, token: str | bytes) -> dict[str, Any]:
        """
        Decodes a given JWT token and verifies its RSA signature

        The token must be signed with the algorithm whitelisted in TokenAlgorithm; any other
        algorithm is rejected before the signature is checked.

        **This is step one of two.** No claim is inspected here, so an EXPIRED token decodes
        successfully - `validate_claims` is what refuses it.

        Args:
            token (str | bytes): The encoded JWT token to be decoded

        Returns:
            dict[str, Any]: The decoded JWT claims

        Raises:
            TokenValidationError: If the token is invalid, malformed, or has a bad signature
            TokenKeyMaterialError: If the public key to verify against could not be obtained - a
                server-side fault, which a route must not answer with 401
        """
        try:
            public_key = RSAKey.import_key(self.key_holder.rsa_public)
        except Exception as err:
            LOGGER.error("[decode_token] The RSA public key could not be used: %s", err, exc_info=True)
            raise TokenKeyMaterialError(err) from err

        try:
            decoded_token = jwt.decode(token, public_key, algorithms=[TokenAlgorithm.RS512])

            return decoded_token.claims
        except Exception as err:
            raise TokenValidationError(err) from err


    def validate_claims(self, claims: dict[str, Any]) -> None:
        """
        Validates the decoded claims regarding their expiration

        **This is step two of two, and the only place a token expires.** `exp` is required: a signed
        token that carries none would otherwise be valid forever, since a claims registry only checks
        what it is given. `iat` and `nbf` are validated when present. All three are compared with
        `TOKEN_TIME_CLAIM_LEEWAY` seconds of tolerance, because the stamping and the validating
        process need not share a clock.

        DataGerry's own `iss` and `DATAGERRY` claims are NOT validated here - they carry a wrapper
        dict rather than a plain value (see `token_constants`), which a registry cannot express; the
        issuer is checked separately by `validate_issuer`

        Args:
            claims (dict[str, Any]): The decoded JWT claims returned by decode_token

        Raises:
            TokenValidationError: If a time claim is invalid, missing (`exp`) or the token has expired
        """
        try:
            time_claims = {
                claim.value: claims[claim.value] for claim in TokenTimeClaim if claim.value in claims
            }
            claims_registry = jwt.JWTClaimsRegistry(
                now=int(time.time()),
                leeway=TOKEN_TIME_CLAIM_LEEWAY,
                **{TokenTimeClaim.EXPIRATION.value: {'essential': True}},
            )
            claims_registry.validate(time_claims)
        except JoseError as err:
            raise TokenValidationError(err) from err
        except Exception as err:
            # A claim of the wrong TYPE (a string 'exp', say) raises out of the registry rather than
            # as a JoseError; it is still nothing but an invalid token
            raise TokenValidationError(err) from err


    def validate_issuer(self, claims: dict[str, Any], expected_issuer: str) -> None:
        """
        Validates that the token was issued by this product

        Kept separate from `validate_claims` because the claim cannot be checked by a claims
        registry: DataGerry stores `iss` as `{'essential': True, 'value': <title>}` rather than as
        the plain string the JWT spec expects, and that shape is token-compatibility contract (see
        `token_constants`). Reading the wrapper's `value` is therefore the only way to check it

        Args:
            claims (dict[str, Any]): The decoded JWT claims returned by decode_token
            expected_issuer (str): The issuer the token has to name - the product title

        Raises:
            TokenValidationError: If the issuer claim is absent, malformed or names something else
        """
        issuer_claim = claims.get(TokenClaim.ISSUER.value)

        if isinstance(issuer_claim, dict):
            issuer = issuer_claim.get(TokenClaimWrapperKey.VALUE.value)
        else:
            # A plain string issuer is what the JWT spec asks for; accepted so the wrapper can be
            # dropped one day without this check having to change with it
            issuer = issuer_claim

        if issuer != expected_issuer:
            raise TokenValidationError(f"Token was not issued by '{expected_issuer}': {issuer!r}!")

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
Implementation of TokenGenerator - the signer of every login token

Two inputs, from two different places:

* the **signing key** is the installation's RSA key, read through `KeyHolder` from the database the
  database manager is bound to - one key for the whole installation, tenants included, because the
  validator of every request reads the same one
* the **token lifetime** is an administrator's setting in the `auth` settings section, which lives in the
  database of the user the token is for: the tenant's database in cloud mode, the one database on
  premise. Reading it from anywhere else would ignore what the tenant configured
"""
from logging import Logger, getLogger
from datetime import datetime, timedelta, timezone
from typing import Any

from joserfc import jwt
from joserfc.jwk import RSAKey

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager

from cmdb import __title__
from cmdb.models.security_models.auth_settings import CmdbAuthSettings
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
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
    DEFAULT_CLAIMS: dict[str, Any] = {
        'iss': {
            'essential': True,
            'value': __title__
        }
    }

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initializes the TokenGenerator

        Reads the two things every token needs once, here: the signing key (see the module docstring)
        and the token lifetime from the `auth` settings of `database`

        Args:
            dbm (MongoDatabaseManager): Database manager; required - the signing key and the settings are
                both read through it
            database (str | None): The database whose `auth` settings decide the token lifetime - the
                user's tenant database in cloud mode. None reads the database manager's own, which is
                the one database on premise
        """
        self.key_holder = KeyHolder(dbm)

        self.header = {
            'alg': TokenAlgorithm.RS512.value
        }

        self.token_lifetime: int = read_token_lifetime(SettingsManager(dbm, database))


    def get_expire_time(self, issued_at: datetime | None = None) -> datetime:
        """
        Calculates when a token issued at `issued_at` expires

        Args:
            issued_at (datetime | None): The issue time; None means now

        Returns:
            datetime: The issue time plus the configured token lifetime
        """
        return (issued_at or datetime.now(timezone.utc)) + timedelta(minutes=self.token_lifetime)


    def generate_token_with_times(
            self,
            payload: dict[str, Any],
            optional_claims: dict[str, Any] | None = None
        ) -> tuple[bytes, int, int]:
        """
        Signs a token and answers it together with the issue and expiry times written into it

        The login response reports when the token expires; taking those times from the claims that were
        signed - rather than computing them a second time - keeps the two from ever disagreeing, even
        across a second boundary

        Args:
            payload (dict[str, Any]): The main payload to be included in the token's claims
            optional_claims (dict[str, Any] | None): Additional claims to be included in the token

        Returns:
            tuple[bytes, int, int]: The encoded token, its `iat` and its `exp` (UTC epoch seconds)
        """
        issued_at: datetime = datetime.now(timezone.utc)
        issued: int = int(issued_at.timestamp())
        expires: int = int(self.get_expire_time(issued_at).timestamp())

        token_claims = {
            'iat': issued,
            'exp': expires,
        }
        payload_claims = {
            'DATAGERRY': {
                'essential': True,
                'value': payload
            }
        }
        claims = {**self.DEFAULT_CLAIMS, **token_claims, **payload_claims, **(optional_claims or {})}
        private_key = RSAKey.import_key(self.key_holder.get_private_key())
        token = jwt.encode(self.header, claims, private_key, algorithms=[TokenAlgorithm.RS512.value])

        return token.encode('utf-8'), issued, expires


    def generate_token(self, payload: dict[str, Any], optional_claims: dict[str, Any] | None = None) -> bytes:
        """
        Generates a signed JWT token from the payload and optional additional claims

        Combines the default claims, the token's own `iat` / `exp` and any optional claims - see
        `generate_token_with_times` for a caller that also needs those two times

        Args:
            payload (dict[str, Any]): The main payload to be included in the token's claims
            optional_claims (dict[str, Any] | None): Additional claims to be included in the token

        Returns:
            bytes: The encoded JWT token as a byte string
        """
        token, _, _ = self.generate_token_with_times(payload, optional_claims)

        return token


def read_token_lifetime(settings_manager: SettingsManager) -> int:
    """
    Reads the token lifetime, in minutes, from the `auth` settings section a SettingsManager addresses

    A missing section, or one without `token_lifetime`, is the default lifetime - the same answer the
    section has when it is read for the login itself (`CmdbAuthSettings.from_data`, not strict). Only the
    lifetime is read: building the whole AuthModule for it cost a provider normalisation per token

    Args:
        settings_manager (SettingsManager): Bound to the database whose `auth` section decides

    Raises:
        AuthSettingsInitError: When the stored section is malformed - as the login would fail on it too

    Returns:
        int: The token lifetime in minutes
    """
    stored: dict[str, Any] = settings_manager.get_section(AUTH_SETTINGS_ID) or {}

    return CmdbAuthSettings.from_data(stored).get_token_lifetime()

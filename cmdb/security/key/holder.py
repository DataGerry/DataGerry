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
Implementation of KeyHolder, and of ``load_key_holder`` - the one way a token signer or verifier gets one

On premise the keypair is read from the ``security`` settings document **once per process and database**
(``read_stored_keypair``): it is written when the database is created and nothing replaces it while the process
runs, so reading it per request - every validator builds a holder - was one Mongo round trip per authenticated
request for a value that never changes. Only a complete keypair is kept; a missing or broken one is read again
next time, so a repaired key needs no restart. A keypair REPLACED in the database by hand (a restored backup) does:
the process keeps the one it read first.

A holder reads its key material in its constructor, so a missing or unreadable key surfaces there. Left raw, that
error is indistinguishable from anything else a request can raise, and a route's catch-all answers it as a bad
credential (401) - which logs the user out over the server's fault. ``load_key_holder`` types it instead: a
``DocumentNetworkError`` when the database server is gone (the app answers 503, try again), a
``TokenKeyMaterialError`` for anything else (500)
"""
from logging import Logger, getLogger
from typing import Any

from flask import current_app

from cmdb.database import MongoDatabaseManager
from cmdb.database.mongo_error_helper import is_database_outage
from cmdb.security.key.security_settings import read_security_setting
from cmdb.security.key.secret_resolver import (
    ASYMMETRIC_KEY_SETTING,
    resolve_secret,
)

from cmdb.errors.database import DocumentNetworkError
from cmdb.errors.security import TokenKeyMaterialError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Environment variables carrying the Base64 keypair on a hosted cloud installation, and the halves
# of the stored keypair document they correspond to
PUBLIC_KEY_ENV_VAR: str = 'DG_RSA_PUBLIC_KEY'
PRIVATE_KEY_ENV_VAR: str = 'DG_RSA_PRIVATE_KEY'
PUBLIC_HALF: str = 'public'
PRIVATE_HALF: str = 'private'

# What an on-premise holder says when the stored keypair it needs is not there
NO_STORED_KEYPAIR_MSG: str = "No RSA keypair is stored in the 'security' settings"
NO_STORED_KEY_HALF_MSG: str = "The RSA keypair stored in the 'security' settings has no '{half}' half"

# The complete stored keypair of each database this process read it from, by database name (read_stored_keypair).
# Filled in each worker on its first request; a dict assignment is atomic, so two requests racing on the first read
# at worst both read it
_STORED_KEYPAIRS: dict[str, dict[str, Any]] = {}


def read_stored_keypair(dbm: MongoDatabaseManager) -> Any:
    """
    The keypair stored in the ``security`` settings of the database manager's default database, read once per process

    A complete keypair - a dict carrying both halves - is kept for the life of the process and answered from memory
    after that. Anything else (no document, no keypair, a missing half) is answered as read and NOT kept, so the next
    call reads again and a repaired keypair takes effect without a restart

    Args:
        dbm (MongoDatabaseManager): The database manager; its default database is the one read

    Returns:
        Any: The stored keypair, or whatever the settings read answered when it is not a complete one
    """
    cached: dict[str, Any] | None = _STORED_KEYPAIRS.get(dbm.db_name)

    if cached is not None:
        return cached

    stored: Any = read_security_setting(dbm, None, ASYMMETRIC_KEY_SETTING)

    if isinstance(stored, dict) and all(stored.get(half) is not None for half in (PUBLIC_HALF, PRIVATE_HALF)):
        _STORED_KEYPAIRS[dbm.db_name] = stored

    return stored


def clear_stored_keypair_cache() -> None:
    """
    Forgets every keypair read so far, so the next holder reads the database again

    For tests: one that patches the settings read must not be answered from a keypair an earlier test left behind
    """
    _STORED_KEYPAIRS.clear()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   KeyHolder - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class KeyHolder:
    """
    Holds the installation's RSA keypair, which signs (private half) and verifies (public half) every login token

    The keys come from one of three sources, picked by the process's mode flags (``secret_resolver.resolve_secret``):

    - **developer cloud stack** (``--cloud --local``): the literal keys carried on the app
      (``current_app.asymmetric_key``)
    - **hosted cloud** (``--cloud``): Base64 in the ``DG_RSA_PUBLIC_KEY`` / ``DG_RSA_PRIVATE_KEY`` environment variables
    - **on premise** (neither flag): the ``security`` document of the settings collection, read once per process
      (``read_stored_keypair``)

    Built through ``load_key_holder``, which types a failure to obtain the keys
    """

    def __init__(self, dbm: MongoDatabaseManager, with_private_key: bool = True) -> None:
        """
        Initializes the KeyHolder instance, loading the RSA keys it is asked for

        Both keys are loaded by default, because a holder is normally built to SIGN. Verifying needs
        the public key alone (`TokenValidator`), so a holder that will never sign asks for
        `with_private_key=False` rather than holding a private key it cannot use - a key that is never
        loaded cannot leak

        Args:
            dbm (MongoDatabaseManager): Reads the stored keypair on premise; unused by the two cloud modes
            with_private_key (bool): Whether to load the private key as well. Defaults to True

        Raises:
            ValueError: When a key cannot be obtained from its source - see ``get_public_key``
            DocumentGetError: When the on-premise settings read fails

        Attributes:
            dbm (MongoDatabaseManager): Reads the stored keypair on premise (``security_settings``), from the
                default database - an on-premise installation has one
            rsa_public (bytes): The RSA public key, PEM - verifies a token's signature
            rsa_private (bytes | None): The RSA private key, PEM - signs a token; None when it was not asked for
        """
        self.dbm: MongoDatabaseManager = dbm
        self._stored_keypair: dict[str, Any] | None = None
        self.rsa_public: bytes = self.get_public_key()
        self.rsa_private: bytes | None = self.get_private_key() if with_private_key else None


    def get_public_key(self) -> bytes:
        """
        Retrieves the RSA public key, from the source the mode picks (see the class docstring)

        Returns:
            bytes: The RSA public key, PEM - decoded from Base64 when it comes from the environment

        Raises:
            ValueError: In hosted cloud when ``DG_RSA_PUBLIC_KEY`` is unset, empty or not valid Base64; on premise
                when no keypair is stored, or the stored one has no public half - each message names which
            DocumentGetError: When the on-premise settings read fails
        """
        return resolve_secret(
            dev_value=lambda: current_app.asymmetric_key[PUBLIC_HALF],
            env_var=PUBLIC_KEY_ENV_VAR,
            label='RSA public key',
            stored_value=lambda: self._stored_half(PUBLIC_HALF),
        )


    def get_private_key(self) -> bytes:
        """
        Retrieves the RSA private key, from the source the mode picks (see the class docstring)

        Returns:
            bytes: The RSA private key, PEM - decoded from Base64 when it comes from the environment

        Raises:
            ValueError: In hosted cloud when ``DG_RSA_PRIVATE_KEY`` is unset, empty or not valid Base64; on premise
                when no keypair is stored, or the stored one has no private half - each message names which
            DocumentGetError: When the on-premise settings read fails
        """
        return resolve_secret(
            dev_value=lambda: current_app.asymmetric_key[PRIVATE_HALF],
            env_var=PRIVATE_KEY_ENV_VAR,
            label='RSA private key',
            stored_value=lambda: self._stored_half(PRIVATE_HALF),
        )


    def _stored_half(self, half: str) -> bytes:
        """
        Reads one half of the stored keypair, through the process-wide copy (``read_stored_keypair``)

        Both halves live in ONE settings document; the holder asks for it at most once, and a complete keypair is
        read from the database once per process - not once per holder, which was once per request

        Args:
            half (str): Which half to read - PUBLIC_HALF or PRIVATE_HALF

        Raises:
            ValueError: When no keypair is stored, or the stored one lacks the half - named, as the hosted cloud
                ``decode_env_secret`` names a missing variable

        Returns:
            bytes: The requested half of the RSA keypair
        """
        if self._stored_keypair is None:
            self._stored_keypair = read_stored_keypair(self.dbm)

        if not isinstance(self._stored_keypair, dict):
            raise ValueError(NO_STORED_KEYPAIR_MSG)

        stored_half: bytes | None = self._stored_keypair.get(half)

        if stored_half is None:
            raise ValueError(NO_STORED_KEY_HALF_MSG.format(half=half))

        return stored_half


def load_key_holder(dbm: MongoDatabaseManager, with_private_key: bool = True) -> KeyHolder:
    """
    Builds a KeyHolder, typing any failure to obtain its key material

    Args:
        dbm (MongoDatabaseManager): The database manager the holder reads the stored keypair through
        with_private_key (bool): Whether to load the private key as well (``KeyHolder``)

    Raises:
        DocumentNetworkError: When the database server was lost while the key was read (``is_database_outage``) -
            a retryable outage, which the app answers 503
        TokenKeyMaterialError: When the key material could not be obtained for any other reason - the server's
            fault, which a route answers 500, never 401

    Returns:
        KeyHolder: The holder, its keys loaded
    """
    try:
        return KeyHolder(dbm, with_private_key=with_private_key)
    except Exception as err:
        if is_database_outage(err):
            LOGGER.error("[load_key_holder] The database was lost while the RSA key was read: %s", err, exc_info=True)
            raise DocumentNetworkError(err) from err

        LOGGER.error("[load_key_holder] The RSA key material could not be obtained: %s", err, exc_info=True)
        raise TokenKeyMaterialError(err) from err

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
Where DataGerry's key material comes from, in one place

Three secrets follow the same resolution ladder - the symmetric AES key that keys the password HMAC,
and the two halves of the RSA keypair that signs and verifies tokens:

1. **cloud + local** (a developer's own stack): the value carried on the app
2. **cloud** (hosted): a Base64 value in an environment variable
3. **on-premise**: the ``security`` section of the settings collection

The ladder lives here once. Written out per caller it differs only in a dict key and an environment
variable name, which is how one missing-environment-variable bug comes to exist in several copies at
once.

Nothing here imports from ``cmdb.manager``: ``KeyHolder`` and ``SecurityManager`` sit on opposite
sides of that package boundary (``cmdb.security.key`` imports the manager layer, and the manager layer
imports this module), so a manager import here would close the cycle. The settings read is therefore
passed in as a callable rather than performed here, which also keeps it LAZY - the on-premise branch
must not touch the database when the answer comes from an environment variable
"""
import base64
import binascii
import os
from logging import Logger, getLogger
from typing import Callable

from Crypto import Random
from flask import current_app
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'SECURITY_SECTION',
    'SYMMETRIC_KEY_SETTING',
    'ASYMMETRIC_KEY_SETTING',
    'SYMMETRIC_KEY_BYTES',
    'decode_env_secret',
    'new_symmetric_aes_key',
    'resolve_secret',
]

# The settings section every key is stored in, and the keys within it. Named here because the manager
# layer and the key package both address them
SECURITY_SECTION: str = 'security'
SYMMETRIC_KEY_SETTING: str = 'symmetric_aes_key'
ASYMMETRIC_KEY_SETTING: str = 'asymmetric_key'

# Length of a generated symmetric key. 32 bytes = AES-256, and the HMAC-SHA256 that keys password
# storage takes it as its key
SYMMETRIC_KEY_BYTES: int = 32


def decode_env_secret(env_var: str, label: str) -> bytes:
    """
    Reads a Base64 secret from an environment variable

    Both failures answer the same way - a ValueError naming the variable - because both are the same
    operator mistake seen from different angles. Left to `b64decode`, the malformed case raises
    `binascii.Error` out of a login request and surfaces as a 500 that says nothing about the
    environment

    Args:
        env_var (str): Name of the environment variable holding the Base64 value
        label (str): What the secret is, for the error message (e.g. 'RSA public key')

    Raises:
        ValueError: When the variable is unset, empty, or does not hold valid Base64

    Returns:
        bytes: The decoded secret
    """
    raw: str | None = os.getenv(env_var)

    if not raw:
        LOGGER.error("[decode_env_secret] No %s provided via '%s'!", label, env_var)
        raise ValueError(f"No {label} provided via the '{env_var}' environment variable")

    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as err:
        LOGGER.error("[decode_env_secret] The %s in '%s' is not valid Base64!", label, env_var)
        raise ValueError(f"The {label} in the '{env_var}' environment variable is not valid Base64") from err


def resolve_secret(
        dev_value: Callable[[], bytes],
        env_var: str,
        label: str,
        stored_value: Callable[[], bytes]) -> bytes:
    """
    Resolves one secret from whichever source the current mode designates

    Both sources are callables so neither is evaluated unless it is the one that applies: reading the
    settings collection to answer a question the environment already answers would be a database round
    trip per token.

    Args:
        dev_value (Callable[[], bytes]): Supplies the value carried on the app (cloud + local)
        env_var (str): Environment variable holding the Base64 value (cloud, hosted)
        label (str): What the secret is, for error messages
        stored_value (Callable[[], bytes]): Supplies the value from the settings collection
            (on-premise)

    Raises:
        ValueError: In hosted cloud mode when the environment variable is unset or malformed

    Returns:
        bytes: The resolved secret
    """
    if current_app.cloud_mode:
        if current_app.local_mode:
            return dev_value()

        return decode_env_secret(env_var, label)

    return stored_value()


def new_symmetric_aes_key() -> bytes:
    """
    Generates a fresh symmetric key

    The single definition of what such a key is. Two call sites create one - the first-boot key
    generation and the manager's lazy fallback - and they used to spell the length out separately

    Returns:
        bytes: SYMMETRIC_KEY_BYTES of randomness
    """
    return Random.get_random_bytes(SYMMETRIC_KEY_BYTES)

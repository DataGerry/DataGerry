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
Unit tests for cmdb.security.license.license_constants

Verifies the shipped crypto material is usable as embedded (the RSA public key parses as a
2048-bit public-only key; the HMAC secret is a non-empty ASCII string) and pins the
fingerprint fallback token. Enum value-contracts live in the central tripwire. Pure tests
"""
from Crypto.PublicKey import RSA

from cmdb.security.license.license_constants import (
    FINGERPRINT_FALLBACK,
    LICENSE_HMAC_SECRET,
    LICENSE_PUBLIC_KEY_PEM,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Expected RSA modulus size of the shipped public key (must match the generator's RSA_KEY_SIZE_BITS)
EXPECTED_RSA_KEY_SIZE_BITS: int = 2048


# -------------------------------------------------------------------------------------------------------------------- #
#                                            shipped RSA public key                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_shipped_public_key_parses_as_rsa_key() -> None:
    """The embedded PEM imports without error as an RSA key"""
    key = RSA.import_key(LICENSE_PUBLIC_KEY_PEM)

    assert key is not None


def test_shipped_public_key_is_2048_bits() -> None:
    """The embedded public key has the RSA-2048 modulus required for OpenCelium block-walk parity"""
    key = RSA.import_key(LICENSE_PUBLIC_KEY_PEM)

    assert key.size_in_bits() == EXPECTED_RSA_KEY_SIZE_BITS


def test_shipped_public_key_carries_no_private_material() -> None:
    """The shipped key is public-only - the license-minting private key must never be embedded"""
    key = RSA.import_key(LICENSE_PUBLIC_KEY_PEM)

    assert key.has_private() is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                              shipped HMAC secret                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_shipped_hmac_secret_is_non_empty_string() -> None:
    """The HMAC secret is a non-empty string so it can be used directly as UTF-8 key bytes"""
    assert isinstance(LICENSE_HMAC_SECRET, str)
    assert LICENSE_HMAC_SECRET != ''


def test_shipped_hmac_secret_is_ascii() -> None:
    """The HMAC secret is plain ASCII (URL-safe Base64), so UTF-8 encoding is unambiguous"""
    assert LICENSE_HMAC_SECRET.isascii()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            fingerprint fallback                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_fingerprint_fallback_token() -> None:
    """The unresolved-field fallback is the literal '0' OpenCelium uses"""
    assert FINGERPRINT_FALLBACK == '0'

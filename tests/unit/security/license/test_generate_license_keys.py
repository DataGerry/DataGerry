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
Unit tests for cmdb.security.license.tooling.generate_license_keys

Verifies the dev key generator mints a usable RSA-4096 keypair (private decrypts what the public
encrypts; the public half is public-only), that the HMAC secret is random and non-empty, and that
write_artifacts lays the three files down with the expected contents. Pure tests (tmp_path only)
"""
from pathlib import Path

from Crypto.PublicKey import RSA

from cmdb.security.license.tooling import generate_license_keys as gen
# -------------------------------------------------------------------------------------------------------------------- #

# Expected RSA modulus size minted by the generator
EXPECTED_RSA_KEY_SIZE_BITS: int = 4096


# -------------------------------------------------------------------------------------------------------------------- #
#                                            RSA keypair generation                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_generate_rsa_keypair_returns_4096_bit_private_and_public() -> None:
    """The keypair is RSA-4096: the private half carries private material, the public half does not"""
    private_pem, public_pem = gen.generate_rsa_keypair()

    private_key = RSA.import_key(private_pem)
    public_key = RSA.import_key(public_pem)

    assert private_key.size_in_bits() == EXPECTED_RSA_KEY_SIZE_BITS
    assert public_key.size_in_bits() == EXPECTED_RSA_KEY_SIZE_BITS
    assert private_key.has_private() is True
    assert public_key.has_private() is False


def test_generate_rsa_keypair_public_matches_private() -> None:
    """The exported public key is the public half of the exported private key (same modulus)"""
    private_pem, public_pem = gen.generate_rsa_keypair()

    private_key = RSA.import_key(private_pem)
    public_key = RSA.import_key(public_pem)

    assert public_key.n == private_key.n
    assert public_key.e == private_key.e


def test_generate_rsa_keypair_produces_distinct_keys() -> None:
    """Two calls produce different keys (real key generation, not a constant)"""
    first_private, _ = gen.generate_rsa_keypair()
    second_private, _ = gen.generate_rsa_keypair()

    assert RSA.import_key(first_private).n != RSA.import_key(second_private).n


# -------------------------------------------------------------------------------------------------------------------- #
#                                              HMAC secret                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_generate_hmac_secret_is_non_empty_ascii() -> None:
    """The secret is a non-empty ASCII string usable directly as UTF-8 key bytes"""
    secret = gen.generate_hmac_secret()

    assert isinstance(secret, str)
    assert secret != ''
    assert secret.isascii()


def test_generate_hmac_secret_is_random() -> None:
    """Successive secrets differ"""
    assert gen.generate_hmac_secret() != gen.generate_hmac_secret()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            artifact writing                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_write_artifacts_writes_three_files_with_contents(tmp_path: Path) -> None:
    """All three artifacts are written into the output dir with the supplied contents"""
    out_dir = tmp_path / 'keys'

    gen.write_artifacts(out_dir, b'PRIVATE-PEM', b'PUBLIC-PEM', 'the-secret')

    assert (out_dir / gen.PRIVATE_KEY_FILENAME).read_bytes() == b'PRIVATE-PEM'
    assert (out_dir / gen.PUBLIC_KEY_FILENAME).read_bytes() == b'PUBLIC-PEM'
    assert (out_dir / gen.HMAC_SECRET_FILENAME).read_text(encoding='utf-8') == 'the-secret'


def test_write_artifacts_creates_missing_output_dir(tmp_path: Path) -> None:
    """A non-existent (nested) output dir is created on demand"""
    out_dir = tmp_path / 'nested' / 'keys'

    gen.write_artifacts(out_dir, b'priv', b'pub', 'secret')

    assert out_dir.is_dir()

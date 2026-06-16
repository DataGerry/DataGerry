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
Dev-only generator for DataGerry's license crypto material (license feature part P0)

This script mints the key material the license feature is built on:
  * a 2048-bit RSA keypair (the license generator/portal encrypts entitlements with the
    PRIVATE key; the running DataGerry backend decrypts them with the PUBLIC key - the
    homemade "signature" scheme inherited from OpenCelium for parity), and
  * a random HMAC secret used for machine binding and the counter tamper-seal.

Only the PUBLIC key and the HMAC secret are shipped, embedded into
`cmdb/security/license/license_constants.py`. The PRIVATE key must never reach a customer install
(it is the license-minting key and belongs only with the generator/portal), so the default output
directory is the gitignored build dir `target/`, never the package itself.

Usage (run from the repository root):
    python3 -m cmdb.security.license.tooling.generate_license_keys [--out-dir target/license_keys]

Outputs (into --out-dir):
    license_private_key.pem   PEM private key   (NEVER ship / NEVER commit)
    license_public_key.pem    PEM public key    (gets embedded into license_constants.py)
    license_hmac_secret.txt    HMAC secret       (gets embedded into license_constants.py)

After running, paste the public key and the HMAC secret into license_constants.py
(LICENSE_PUBLIC_KEY_PEM and LICENSE_HMAC_SECRET); the script prints a ready-to-paste snippet.
"""
import argparse
import secrets
from pathlib import Path

from Crypto.PublicKey import RSA
# -------------------------------------------------------------------------------------------------------------------- #

# RSA modulus size in bits; must stay 2048 for OpenCelium wire-format parity (256-byte blocks)
RSA_KEY_SIZE_BITS: int = 2048

# Number of random bytes in the generated HMAC secret before URL-safe Base64 encoding
HMAC_SECRET_BYTES: int = 32

# Default directory the generated artifacts are written to (gitignored build dir, relative to repo root)
DEFAULT_OUTPUT_DIR: str = 'target/license_keys'

PRIVATE_KEY_FILENAME: str = 'license_private_key.pem'
PUBLIC_KEY_FILENAME: str = 'license_public_key.pem'
HMAC_SECRET_FILENAME: str = 'license_hmac_secret.txt'


def generate_rsa_keypair() -> tuple[bytes, bytes]:
    """
    Generates a fresh RSA keypair for license signing

    Returns:
        tuple[bytes, bytes]: (private_key_pem, public_key_pem) - both PEM-encoded
    """
    key = RSA.generate(RSA_KEY_SIZE_BITS)
    private_key_pem = key.export_key()
    public_key_pem = key.publickey().export_key()

    return private_key_pem, public_key_pem


def generate_hmac_secret() -> str:
    """
    Generates a random URL-safe HMAC secret string

    The value is plain ASCII so it can be embedded as a string constant and used directly as
    the UTF-8 key bytes for HMAC-SHA256 (matching how OpenCelium treats its string secret)

    Returns:
        str: A URL-safe Base64 secret derived from HMAC_SECRET_BYTES random bytes
    """
    return secrets.token_urlsafe(HMAC_SECRET_BYTES)


def write_artifacts(out_dir: Path, private_key_pem: bytes, public_key_pem: bytes, hmac_secret: str) -> None:
    """
    Writes the generated key material to disk

    Args:
        out_dir (Path): Directory the artifacts are written into (created if missing)
        private_key_pem (bytes): PEM-encoded RSA private key
        public_key_pem (bytes): PEM-encoded RSA public key
        hmac_secret (str): The HMAC secret string
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / PRIVATE_KEY_FILENAME).write_bytes(private_key_pem)
    (out_dir / PUBLIC_KEY_FILENAME).write_bytes(public_key_pem)
    (out_dir / HMAC_SECRET_FILENAME).write_text(hmac_secret, encoding='utf-8')


def print_constants_snippet(public_key_pem: bytes, hmac_secret: str) -> None:
    """
    Prints a ready-to-paste snippet for license_constants.py

    Args:
        public_key_pem (bytes): PEM-encoded RSA public key
        hmac_secret (str): The HMAC secret string
    """
    print('\n# ---- paste the following into cmdb/security/license/license_constants.py ----\n')
    print('LICENSE_PUBLIC_KEY_PEM: str = """\\\n' + public_key_pem.decode('utf-8') + '"""\n')
    print(f"LICENSE_HMAC_SECRET: str = '{hmac_secret}'\n")


def main() -> None:
    """
    Parses CLI args, generates the key material, writes it to disk and prints a paste snippet
    """
    parser = argparse.ArgumentParser(
        description="Generate DataGerry license crypto material (RSA keypair + HMAC secret)",
    )
    parser.add_argument('--out-dir', default=DEFAULT_OUTPUT_DIR, help="Directory for the generated artifacts")
    args = parser.parse_args()

    private_key_pem, public_key_pem = generate_rsa_keypair()
    hmac_secret = generate_hmac_secret()

    out_dir = Path(args.out_dir)
    write_artifacts(out_dir, private_key_pem, public_key_pem, hmac_secret)

    print(f"Wrote {PRIVATE_KEY_FILENAME}, {PUBLIC_KEY_FILENAME} and {HMAC_SECRET_FILENAME} to {out_dir.resolve()}")
    print("KEEP THE PRIVATE KEY SECRET - it is the license-minting key and must never ship to a customer install.")
    print_constants_snippet(public_key_pem, hmac_secret)


if __name__ == '__main__':
    main()

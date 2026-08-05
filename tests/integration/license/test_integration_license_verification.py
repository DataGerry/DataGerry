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
Integration test for the license verification chain against the real activation-request store

Wires verify_license (P11) to the real LicenseActivationRequestsManager (P9) on a live MongoDB: a
license minted (P7) bound to a request actually created and persisted by the manager verifies as
VALID via the real findByHmac, while a license bound to an unknown hmac is rejected. Uses an
in-test keypair so it does not depend on the gitignored dev key material
"""
import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_activation_requests_manager import LicenseActivationRequestsManager
from cmdb.security.license.license_constants import ActivationRequestKey, LicenseTier, LicenseVerificationStatus
from cmdb.security.license.tooling.license_generator import build_entitlement, mint_license_blob
from cmdb.security.license.verification import verify_license
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048
NOW_MS: int = 1_700_000_000_000
PAST_MS: int = NOW_MS - 1_000
NO_EXPIRY: int = 0

FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-verify-int',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-verify-int',
    ActivationRequestKey.COMPUTER_NAME: 'host-verify-int',
}


@pytest.fixture(name='rsa_keypair', scope='module')
def fixture_rsa_keypair() -> RsaKey:
    """A single RSA-2048 keypair shared across the module"""
    return RSA.generate(RSA_KEY_SIZE_BITS)


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> LicenseActivationRequestsManager:
    """Provides a LicenseActivationRequestsManager bound to the test database"""
    return LicenseActivationRequestsManager(database_manager, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the activation-request collection after each test"""
    yield
    database_manager.get_collection(LicenseActivationRequestsManager.COLLECTION, database_name).delete_many({})


def _public_pem(keypair: RsaKey) -> str:
    """PEM of a keypair's public half"""
    return keypair.publickey().export_key().decode('utf-8')


def test_license_bound_to_stored_request_verifies_valid(
    manager: LicenseActivationRequestsManager,
    rsa_keypair: RsaKey,
) -> None:
    """A license bound to a request the manager actually persisted verifies as VALID via real findByHmac"""
    request = manager.create_activation_request(FINGERPRINT)
    entitlement = build_entitlement(license_type=LicenseTier.BUSINESS.value, hmac_value=request.hmac,
                                    start_date=PAST_MS, end_date=NO_EXPIRY)
    blob = mint_license_blob(entitlement, rsa_keypair)

    result = verify_license(blob, manager, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.VALID
    assert result.entitlement.license_type == LicenseTier.BUSINESS.value


def test_license_with_unknown_hmac_is_rejected(
    manager: LicenseActivationRequestsManager,
    rsa_keypair: RsaKey,
) -> None:
    """A license whose hmac matches no persisted request is rejected (nothing stored)"""
    entitlement = build_entitlement(hmac_value='unbound-hmac', start_date=PAST_MS, end_date=NO_EXPIRY)
    blob = mint_license_blob(entitlement, rsa_keypair)

    result = verify_license(blob, manager, now_ms=NOW_MS, public_key_pem=_public_pem(rsa_keypair))

    assert result.status == LicenseVerificationStatus.NO_ACTIVATION_REQUEST

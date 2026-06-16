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
Integration test for LicenseService against a real MongoDB

Exercises the full activate -> resolve -> deactivate cycle end to end: a license minted (P7) and
bound to a request the service actually persisted activates and is reflected as the live tier with
its features unlocked; an unbound license is rejected and not stored; and deactivation reverts the
install to the free tier. Uses an in-test keypair via the injectable public key, so it runs in CI
without the gitignored dev key
"""
import pytest
from Crypto.PublicKey import RSA
from Crypto.PublicKey.RSA import RsaKey

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_activation_requests_manager import LicenseActivationRequestsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import ActivationRequestKey, LicenseFeature, LicenseTier
from cmdb.security.license.tooling.license_generator import build_entitlement, mint_license_blob
# -------------------------------------------------------------------------------------------------------------------- #

RSA_KEY_SIZE_BITS: int = 2048
PAST_MS: int = 1_000_000_000_000  # 2001, safely before "now"
NO_EXPIRY: int = 0

FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-svc-int',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-svc-int',
    ActivationRequestKey.COMPUTER_NAME: 'host-svc-int',
}


@pytest.fixture(name='rsa_keypair', scope='module')
def fixture_rsa_keypair() -> RsaKey:
    """A single RSA-2048 keypair shared across the module"""
    return RSA.generate(RSA_KEY_SIZE_BITS)


@pytest.fixture(name='service')
def fixture_service(database_manager: MongoDatabaseManager, database_name: str, rsa_keypair: RsaKey) -> LicenseService:
    """A LicenseService bound to the test database, verifying with the in-test public key"""
    public_pem = rsa_keypair.publickey().export_key().decode('utf-8')
    return LicenseService(database_manager, database_name, public_key_pem=public_pem)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the license collections after each test"""
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    database_manager.get_collection(LicenseActivationRequestsManager.COLLECTION, database_name).delete_many({})


def _bound_blob(service: LicenseService, rsa_keypair: RsaKey, tier: str) -> str:
    """Creates an activation request via the service and mints a license bound to it"""
    request = service.activation_requests_manager.create_activation_request(FINGERPRINT)
    entitlement = build_entitlement(license_type=tier, hmac_value=request.hmac, start_date=PAST_MS, end_date=NO_EXPIRY)
    return mint_license_blob(entitlement, rsa_keypair)


def test_activate_makes_license_the_live_tier(service: LicenseService, rsa_keypair: RsaKey) -> None:
    """Activating a valid license makes it the live tier with its features unlocked"""
    blob = _bound_blob(service, rsa_keypair, LicenseTier.BUSINESS.value)

    result = service.activate(blob)

    assert result.is_valid is True
    assert service.is_active() is True
    assert service.current_tier() == LicenseTier.BUSINESS.value
    assert service.has_feature(LicenseFeature.ISMS) is True


def test_unbound_license_is_rejected_and_not_stored(service: LicenseService, rsa_keypair: RsaKey) -> None:
    """A license whose hmac matches no stored request is not activated"""
    entitlement = build_entitlement(hmac_value='unbound', start_date=PAST_MS, end_date=NO_EXPIRY)
    blob = mint_license_blob(entitlement, rsa_keypair)

    result = service.activate(blob)

    assert result.is_valid is False
    assert service.is_active() is False
    assert service.current_tier() == LicenseTier.FREE.value


def test_activate_overwrites_previous_license(service: LicenseService, rsa_keypair: RsaKey) -> None:
    """Activating a second valid license replaces the first as the live tier"""
    service.activate(_bound_blob(service, rsa_keypair, LicenseTier.CORE.value))
    assert service.current_tier() == LicenseTier.CORE.value

    service.activate(_bound_blob(service, rsa_keypair, LicenseTier.BUSINESS.value))

    assert service.is_active() is True
    assert service.current_tier() == LicenseTier.BUSINESS.value


def test_deactivate_reverts_to_free(service: LicenseService, rsa_keypair: RsaKey) -> None:
    """Deactivating an active license reverts the install to the free tier"""
    service.activate(_bound_blob(service, rsa_keypair, LicenseTier.CORE.value))

    assert service.is_active() is True

    service.deactivate()

    assert service.is_active() is False
    assert service.current_tier() == LicenseTier.FREE.value
    assert service.current_status() is None

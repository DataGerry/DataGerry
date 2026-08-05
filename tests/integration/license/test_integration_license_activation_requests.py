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
Integration tests for LicenseActivationRequestsManager against a real MongoDB

Validates the persistence cycle end to end: a created request is stored with camelCase wire keys
plus a storage-only created_at (confirming the ActivationRequestKey enum keys serialise to their
string values in BSON), is retrievable by id and by hmac, evaluates lazy TTL expiry against the
stored timestamp, and is removable
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_activation_requests_manager import (
    ACTIVATION_CREATED_AT_KEY,
    LicenseActivationRequestsManager,
)
from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
# -------------------------------------------------------------------------------------------------------------------- #

TTL_SECONDS: int = 3600

FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'machine-int-1',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-int-1',
    ActivationRequestKey.COMPUTER_NAME: 'host-int-1',
}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> LicenseActivationRequestsManager:
    """Provides a LicenseActivationRequestsManager bound to the test database"""
    return LicenseActivationRequestsManager(database_manager, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the activation-request collection after each test"""
    yield
    database_manager.get_collection(LicenseActivationRequestsManager.COLLECTION, database_name).delete_many({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          create & retrieve                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_create_persists_wire_document_with_created_at(manager: LicenseActivationRequestsManager) -> None:
    """A created request is stored with camelCase wire keys plus the storage-only created_at"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    stored = manager.get_by_request_id(request.request_id)

    assert stored is not None
    # The enum schema keys persisted as their plain camelCase string values
    assert stored['machineUuid'] == 'machine-int-1'
    assert stored['status'] == ActivationRequestStatus.PENDING.value
    assert stored['ttl'] == TTL_SECONDS
    assert ACTIVATION_CREATED_AT_KEY in stored


def test_create_assigns_public_id(manager: LicenseActivationRequestsManager) -> None:
    """The stored document carries an integer public_id (the collection uses the public_id counter)"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    stored = manager.get_by_request_id(request.request_id)

    assert isinstance(stored['public_id'], int)


def test_create_supersedes_prior_pending_requests(manager: LicenseActivationRequestsManager) -> None:
    """Creating a new request flips every prior PENDING request to EXPIRED; only the newest is PENDING"""
    first = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)
    second = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    first_stored = manager.get_by_request_id(first.request_id)
    second_stored = manager.get_by_request_id(second.request_id)

    assert first_stored['status'] == ActivationRequestStatus.EXPIRED.value
    assert second_stored['status'] == ActivationRequestStatus.PENDING.value


def test_created_hmac_binds_the_fingerprint(manager: LicenseActivationRequestsManager) -> None:
    """The stored hmac is the machine-binding HMAC over the fingerprint and the issued id"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    assert request.hmac == machine_binding_hmac(FINGERPRINT, request.request_id)


def test_get_by_hmac_finds_the_request(manager: LicenseActivationRequestsManager) -> None:
    """A stored request is retrievable by its machine-binding hmac (P11 findByHmac)"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    found = manager.get_by_hmac(request.hmac)

    assert found is not None
    assert found[ActivationRequestKey.ID] == request.request_id


def test_get_by_request_id_missing_returns_none(manager: LicenseActivationRequestsManager) -> None:
    """An unknown request id resolves to None"""
    assert manager.get_by_request_id('does-not-exist') is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          lazy TTL & delete                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_is_document_expired_uses_stored_created_at(manager: LicenseActivationRequestsManager) -> None:
    """Expiry is decided from the stored created_at plus ttl"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)
    stored = manager.get_by_request_id(request.request_id)
    created_at = stored[ACTIVATION_CREATED_AT_KEY]

    assert manager.is_document_expired(stored, now=created_at + TTL_SECONDS - 1) is False
    assert manager.is_document_expired(stored, now=created_at + TTL_SECONDS) is True


def test_delete_by_request_id_removes_the_request(manager: LicenseActivationRequestsManager) -> None:
    """Deleting by id removes the stored request"""
    request = manager.create_activation_request(FINGERPRINT, ttl=TTL_SECONDS)

    manager.delete_by_request_id(request.request_id)

    assert manager.get_by_request_id(request.request_id) is None

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
Functional tests for the license (entitlement) routes over HTTP

GET /license/current always answers (free default when none active), POST /license/activate rejects
an undecryptable blob with 400, and a valid activate -> current -> delete cycle flips the live tier
and reverts to free. The valid path monkeypatches verify_license (the route resolves with the
shipped public key whose private half is not in CI); the reject path exercises real crypto. Also
covers the on-premise 404 guard and request-body validation
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager import license_service as svc_module
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.interface.rest_api.routes.cmdb_license import license_routes as routes_module
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import LicenseTier, LicenseVerificationStatus
from cmdb.security.license.verification import LicenseVerificationResult
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATE_LICENSE_ROUTE,
    CURRENT_LICENSE_ROUTE,
    CurrentLicenseResponseKey,
    LicenseUploadKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

CURRENT_URL: str = f'/license{CURRENT_LICENSE_ROUTE}'
ACTIVATE_URL: str = f'/license{ACTIVATE_LICENSE_ROUTE}'
RESULT_KEY: str = 'result'


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the active-license collection after each test"""
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


def _force_valid(monkeypatch: pytest.MonkeyPatch, tier: str, features: list[str] | None = None) -> None:
    """Makes the service's verify_license accept any blob as a license of the given tier"""
    entitlement = LicenseEntitlement(hmac='bind', license_type=tier, features=features)
    result = LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement)
    monkeypatch.setattr(svc_module, 'verify_license', lambda *args, **kwargs: result)


def _force_valid_by_blob(monkeypatch: pytest.MonkeyPatch, blob_to_tier: dict) -> None:
    """Makes verify_license accept each blob as a valid license of the blob's mapped tier"""
    def _verify(blob: str, *_args: object, **_kwargs: object) -> LicenseVerificationResult:
        entitlement = LicenseEntitlement(hmac='bind', license_type=blob_to_tier[blob])
        return LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement)

    monkeypatch.setattr(svc_module, 'verify_license', _verify)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          GET current license                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_current_license_defaults_to_free(rest_api) -> None:
    """With no license active the route returns the free entitlement and is_active false"""
    response = rest_api.get(CURRENT_URL)

    assert response.status_code == HTTPStatus.OK
    payload = response.json[RESULT_KEY]
    assert payload[CurrentLicenseResponseKey.IS_ACTIVE.value] is False
    assert payload[CurrentLicenseResponseKey.STATUS.value] is None
    assert payload['type'] == LicenseTier.FREE.value


# -------------------------------------------------------------------------------------------------------------------- #
#                                          POST activate                                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_activate_rejects_undecryptable_blob(rest_api) -> None:
    """An undecryptable blob is rejected with HTTP 400 (real verification)"""
    response = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'not-a-real-blob!!!'})

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_activate_rejects_missing_blob(rest_api) -> None:
    """A request body without a blob fails schema validation"""
    response = rest_api.post(ACTIVATE_URL, json={})

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_activate_current_delete_cycle(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Activating a (forced-valid) license makes it live; deleting it reverts to free"""
    _force_valid(monkeypatch, LicenseTier.BUSINESS.value, features=['isms', 'ipam'])

    activate = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})
    assert activate.status_code == HTTPStatus.OK
    assert activate.json[RESULT_KEY][CurrentLicenseResponseKey.IS_ACTIVE.value] is True
    entitlement = activate.json[RESULT_KEY]
    assert entitlement['type'] == LicenseTier.BUSINESS.value
    assert entitlement['features'] == ['isms', 'ipam']

    current = rest_api.get(CURRENT_URL)
    assert current.json[RESULT_KEY][CurrentLicenseResponseKey.IS_ACTIVE.value] is True

    deleted = rest_api.delete(CURRENT_URL)
    assert deleted.status_code == HTTPStatus.OK
    assert deleted.json[RESULT_KEY][CurrentLicenseResponseKey.IS_ACTIVE.value] is False
    assert deleted.json[RESULT_KEY]['type'] == LicenseTier.FREE.value


def test_activate_overwrites_current_license(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploading a second valid license replaces the current one"""
    _force_valid_by_blob(monkeypatch, {
        'core-blob': LicenseTier.CORE.value,
        'business-blob': LicenseTier.BUSINESS.value,
    })

    first = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'core-blob'})
    assert first.json[RESULT_KEY]['type'] == LicenseTier.CORE.value

    second = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'business-blob'})
    assert second.json[RESULT_KEY]['type'] == LicenseTier.BUSINESS.value

    current = rest_api.get(CURRENT_URL)
    assert current.json[RESULT_KEY]['type'] == LicenseTier.BUSINESS.value


# -------------------------------------------------------------------------------------------------------------------- #
#                                          on-premise guard                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_current_license_hidden_in_non_on_premise_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The current-license route is on-premise only and returns 404 in local (cloud) mode"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    response = rest_api.get(CURRENT_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                          internal error handling                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _raise_on_get_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes resolving the LicenseService raise an unexpected error inside the route handlers"""
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError('manager exploded')

    monkeypatch.setattr(routes_module.ManagerProvider, 'get_manager', _boom)


def test_get_current_returns_500_on_unexpected_error(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected failure in GET current is reported as a 500"""
    _raise_on_get_manager(monkeypatch)

    assert rest_api.get(CURRENT_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_delete_current_returns_500_on_unexpected_error(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected failure in DELETE current is reported as a 500"""
    _raise_on_get_manager(monkeypatch)

    assert rest_api.delete(CURRENT_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_activate_returns_500_on_unexpected_error(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected failure in POST activate (after body validation) is reported as a 500"""
    _raise_on_get_manager(monkeypatch)

    response = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

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
    LICENSE_ENTITLEMENTS_ROUTE,
    CurrentLicenseResponseKey,
    LicenseEntitlementsResponseKey,
    LicenseUploadKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

CURRENT_URL: str = f'/license{CURRENT_LICENSE_ROUTE}'
ACTIVATE_URL: str = f'/license{ACTIVATE_LICENSE_ROUTE}'
ENTITLEMENTS_URL: str = f'/license{LICENSE_ENTITLEMENTS_ROUTE}'
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                          GET entitlements                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_entitlements_on_the_free_default(rest_api) -> None:
    """With no license active the route answers inactive, on the free tier, with no features"""
    response = rest_api.get(ENTITLEMENTS_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.json[RESULT_KEY] == {
        LicenseEntitlementsResponseKey.IS_ACTIVE.value: False,
        LicenseEntitlementsResponseKey.TYPE.value: LicenseTier.FREE.value,
        LicenseEntitlementsResponseKey.FEATURES.value: [],
    }


def test_entitlements_report_an_active_license(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An activated license is reported active, with its tier and exactly the features it grants"""
    _force_valid(monkeypatch, LicenseTier.BUSINESS.value, features=['isms', 'ipam'])
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    response = rest_api.get(ENTITLEMENTS_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.json[RESULT_KEY] == {
        LicenseEntitlementsResponseKey.IS_ACTIVE.value: True,
        LicenseEntitlementsResponseKey.TYPE.value: LicenseTier.BUSINESS.value,
        LicenseEntitlementsResponseKey.FEATURES.value: ['isms', 'ipam'],
    }


@pytest.mark.parametrize('tier', [LicenseTier.CORE.value, LicenseTier.BUSINESS.value,
                                  LicenseTier.CORPORATE.value])
def test_entitlements_report_each_tier(rest_api, monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    """The tier is what a screen names the plan by, so every one of them has to come through"""
    _force_valid(monkeypatch, tier)
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    assert rest_api.get(ENTITLEMENTS_URL).json[RESULT_KEY][
        LicenseEntitlementsResponseKey.TYPE.value] == tier


def test_an_expired_license_reports_the_free_tier(rest_api, monkeypatch) -> None:
    """A lapsed license degrades to Community, and the tier says so rather than the old plan"""
    _force_valid(monkeypatch, LicenseTier.BUSINESS.value, features=['isms'])
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    expired = LicenseVerificationResult(LicenseVerificationStatus.EXPIRED)
    monkeypatch.setattr(svc_module, 'verify_license', lambda *args, **kwargs: expired)

    body = rest_api.get(ENTITLEMENTS_URL).json[RESULT_KEY]

    assert body[LicenseEntitlementsResponseKey.IS_ACTIVE.value] is False
    assert body[LicenseEntitlementsResponseKey.TYPE.value] == LicenseTier.FREE.value


def test_entitlements_carry_nothing_that_identifies_the_license(rest_api, monkeypatch) -> None:
    """Three keys and no more - no id, no subscription, no binding HMAC, no dates

    The tier IS answered: it names the plan a screen shows and identifies no license. Everything
    that does identify one stays on the right-gated /current route.
    """
    entitlement = LicenseEntitlement(
        hmac='super-secret-binding-hmac',
        license_type=LicenseTier.BUSINESS.value,
        start_date=1700000000000,
        end_date=1900000000000,
        sub_id='sub-4711',
        license_id='lic-0815',
        features=['isms'],
    )
    result = LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement)
    monkeypatch.setattr(svc_module, 'verify_license', lambda *args, **kwargs: result)
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    response = rest_api.get(ENTITLEMENTS_URL)
    body = response.get_data(as_text=True)

    assert set(response.json[RESULT_KEY]) == {
        LicenseEntitlementsResponseKey.IS_ACTIVE.value,
        LicenseEntitlementsResponseKey.TYPE.value,
        LicenseEntitlementsResponseKey.FEATURES.value,
    }
    for secret in ('super-secret-binding-hmac', 'sub-4711', 'lic-0815', '1700000000000', '1900000000000'):
        assert secret not in body


def test_entitlements_agree_with_the_current_license_route(rest_api, monkeypatch) -> None:
    """The two routes read one state, so their is_active and features cannot drift apart"""
    _force_valid(monkeypatch, LicenseTier.BUSINESS.value, features=['isms', 'ipam'])
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    entitlements = rest_api.get(ENTITLEMENTS_URL).json[RESULT_KEY]
    current = rest_api.get(CURRENT_URL).json[RESULT_KEY]

    assert entitlements[LicenseEntitlementsResponseKey.IS_ACTIVE.value] == \
        current[CurrentLicenseResponseKey.IS_ACTIVE.value]
    assert entitlements[LicenseEntitlementsResponseKey.FEATURES.value] == current['features']
    assert entitlements[LicenseEntitlementsResponseKey.TYPE.value] == current['type']


def test_an_expired_license_is_not_active_and_grants_nothing(rest_api, monkeypatch) -> None:
    """Expiry is already inside is_active: a lapsed license reports inactive on the free features"""
    _force_valid(monkeypatch, LicenseTier.BUSINESS.value, features=['isms', 'ipam'])
    rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: 'any-blob'})

    expired = LicenseVerificationResult(LicenseVerificationStatus.EXPIRED)
    monkeypatch.setattr(svc_module, 'verify_license', lambda *args, **kwargs: expired)

    response = rest_api.get(ENTITLEMENTS_URL)

    assert response.json[RESULT_KEY] == {
        LicenseEntitlementsResponseKey.IS_ACTIVE.value: False,
        LicenseEntitlementsResponseKey.TYPE.value: LicenseTier.FREE.value,
        LicenseEntitlementsResponseKey.FEATURES.value: [],
    }


def test_entitlements_require_authentication(rest_api) -> None:
    """No ACL right is required, but a token is"""
    response = rest_api.get(ENTITLEMENTS_URL, environ_overrides={'HTTP_AUTHORIZATION': ''})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_entitlements_hidden_in_non_on_premise_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Like every license route, it is a 404 outside the on-premise version

    Local mode rather than cloud mode, for the same reason the current-license test uses it: cloud
    mode makes `insert_request_user` read a `database` claim the test client's token does not carry,
    so the request would be refused 401 before the guard is reached.
    """
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(ENTITLEMENTS_URL).status_code == HTTPStatus.NOT_FOUND

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
Functional tests for the license activation-request route (GET /license/activation-request)

Drives the route over HTTP with an authenticated admin: it returns 200 with both the activation
request document and its downloadable blob, the blob decodes back to that document, and the
returned hmac is the machine-binding HMAC over the issued fingerprint and id. The deeper crypto /
persistence behaviour is asserted at the unit / integration tiers
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_activation_requests_manager import LicenseActivationRequestsManager
from cmdb.security.license.hmac_binding import machine_binding_hmac
from cmdb.security.license.license_constants import ActivationRequestKey
from cmdb.security.license.transport import decode_json
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATION_REQUEST_ROUTE,
    LicenseActivationResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = f'/license{ACTIVATION_REQUEST_ROUTE}'

# Envelope key wrapping a GetSingleResponse payload
RESULT_KEY: str = 'result'


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears any activation requests created by the route after each test"""
    yield
    database_manager.get_collection(LicenseActivationRequestsManager.COLLECTION, database_name).delete_many({})


def test_get_activation_request_returns_request_and_blob(rest_api) -> None:
    """The route returns 200 with the activation request document and its downloadable blob"""
    response = rest_api.get(ROUTE_URL)

    assert response.status_code == HTTPStatus.OK
    envelope = response.json[RESULT_KEY]
    payload = envelope[LicenseActivationResponseKey.ACTIVATION_REQUEST.value]
    blob = envelope[LicenseActivationResponseKey.BLOB.value]

    assert payload[ActivationRequestKey.STATUS.value] == 'PENDING'
    assert set(payload) == {key.value for key in ActivationRequestKey}
    assert isinstance(blob, str) and blob != ''


def test_blob_decodes_back_to_the_request_document(rest_api) -> None:
    """The returned blob is the Base64+JSON encoding of the returned activation-request document"""
    response = rest_api.get(ROUTE_URL)

    envelope = response.json[RESULT_KEY]
    payload = envelope[LicenseActivationResponseKey.ACTIVATION_REQUEST.value]
    blob = envelope[LicenseActivationResponseKey.BLOB.value]

    assert decode_json(blob) == payload


def test_returned_hmac_binds_the_fingerprint(rest_api) -> None:
    """The returned hmac is the machine-binding HMAC over the request's fingerprint and id"""
    response = rest_api.get(ROUTE_URL)

    payload = response.json[RESULT_KEY][LicenseActivationResponseKey.ACTIVATION_REQUEST.value]
    fingerprint = {
        ActivationRequestKey.MACHINE_UUID: payload[ActivationRequestKey.MACHINE_UUID.value],
        ActivationRequestKey.MAC_ADDRESS: payload[ActivationRequestKey.MAC_ADDRESS.value],
        ActivationRequestKey.SYSTEM_UUID: payload[ActivationRequestKey.SYSTEM_UUID.value],
        ActivationRequestKey.COMPUTER_NAME: payload[ActivationRequestKey.COMPUTER_NAME.value],
    }

    expected = machine_binding_hmac(fingerprint, payload[ActivationRequestKey.ID.value])

    assert payload[ActivationRequestKey.HMAC.value] == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          guards & error handling                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_hidden_in_non_on_premise_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The license route is on-premise only and returns 404 when running in local (cloud) mode"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    response = rest_api.get(ROUTE_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_internal_error_returns_500(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected failure while generating the request is reported as a 500, not a stack trace"""
    from cmdb.interface.rest_api.routes.cmdb_license import license_activation_routes as routes

    def _raise() -> None:
        raise RuntimeError('fingerprint blew up')

    monkeypatch.setattr(routes, 'get_machine_fingerprint', _raise)

    response = rest_api.get(ROUTE_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

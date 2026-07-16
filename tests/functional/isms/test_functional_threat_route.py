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
Functional smoke for the ``/isms/threats`` REST routes

Covers the route-layer concerns on top of the ThreatManager integration suite: HTTP status codes,
schema validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400 mapping, and
the ISMS-specific 400 when deleting a Threat still referenced by a Risk. The routes are ISMS-license
gated, so the license check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsThreat, IsmsRisk
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.threat_manager import (
    ThreatManagerInsertError,
    ThreatManagerGetError,
    ThreatManagerUpdateError,
    ThreatManagerDeleteError,
    ThreatManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/threats'

THREAT_ID_FOR_GET: int = 97101
THREAT_ID_FOR_UPDATE: int = 97102
THREAT_ID_FOR_DELETE: int = 97103
THREAT_ID_FOR_BLOCKED_DELETE: int = 97104
MISSING_THREAT_ID: int = 97199
RISK_ID: int = 97150

# bulk-delete fixtures: two unused threats, one still referenced by a Risk
THREAT_BULK_UNUSED_A: int = 97111
THREAT_BULK_UNUSED_B: int = 97112
THREAT_BULK_USED: int = 97113
BULK_RISK_ID: int = 97151

ALL_THREAT_IDS: list[int] = [
    THREAT_ID_FOR_GET, THREAT_ID_FOR_UPDATE, THREAT_ID_FOR_DELETE, THREAT_ID_FOR_BLOCKED_DELETE,
    THREAT_BULK_UNUSED_A, THREAT_BULK_UNUSED_B, THREAT_BULK_USED,
]
ALL_RISK_IDS: list[int] = [RISK_ID, BULK_RISK_ID]

THREAT_NAME: str = 'Functional Threat'


def _threat_payload(public_id: int, name: str = THREAT_NAME) -> dict[str, Any]:
    """Builds an IsmsThreat body accepted by POST / PUT (name is the only required field)."""
    return {'public_id': public_id, 'name': name}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/threats routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any threats / risks seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsThreat.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_THREAT_IDS}})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})

    _purge()
    yield
    _purge()


def _insert_threat(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts an IsmsThreat doc directly via the collection."""
    database_manager.get_collection(IsmsThreat.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': THREAT_NAME})


def _insert_risk_using_threat(database_manager: MongoDatabaseManager, database_name: str, threat_id: int) -> None:
    """Inserts an IsmsRisk that references the given threat, to trigger the delete guard."""
    database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
        .insert_one({'public_id': RISK_ID, 'threats': [threat_id], 'vulnerabilities': []})


class TestPostThreat:
    """POST /isms/threats/ creates an IsmsThreat."""

    def test_creates_threat(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid body succeeds and the threat becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_threat_payload(THREAT_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_invalid_payload_returns_400(self, rest_api) -> None:
        """A POST missing the required name fails schema validation with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json={'identifier': 'x'}).status_code == HTTPStatus.BAD_REQUEST


class TestGetThreat:
    """GET /isms/threats/<id> and GET /isms/threats/ return the expected envelopes."""

    def test_get_single_returns_threat(self, rest_api,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching threat."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{THREAT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == THREAT_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_THREAT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/threats/ returns a results envelope whose length matches X-Total-Count."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutThreat:
    """PUT /isms/threats/<id> writes the new payload over the existing IsmsThreat."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{THREAT_ID_FOR_UPDATE}',
                                json=_threat_payload(THREAT_ID_FOR_UPDATE, 'Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{THREAT_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent threat returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_THREAT_ID}',
                            json=_threat_payload(MISSING_THREAT_ID)).status_code == HTTPStatus.NOT_FOUND


class TestDeleteThreat:
    """DELETE /isms/threats/<id> removes the threat unless a Risk references it."""

    def test_delete_removes_threat(self, rest_api,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{THREAT_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{THREAT_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent threat returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_THREAT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_blocked_when_used_by_risk_returns_400(self, rest_api,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """Deleting a threat referenced by a Risk returns 400 and the threat is preserved."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_BLOCKED_DELETE)
        _insert_risk_using_threat(database_manager, database_name, THREAT_ID_FOR_BLOCKED_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{THREAT_ID_FOR_BLOCKED_DELETE}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{THREAT_ID_FOR_BLOCKED_DELETE}').status_code == HTTPStatus.OK


class TestDeleteManyThreats:
    """DELETE /isms/threats/delete/<ids> removes unused threats, reports Risk-referenced ones."""

    def test_bulk_delete_removes_unused_and_reports_in_use(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Unused threats are deleted; the one referenced by a Risk is kept and reported in_use."""
        _insert_threat(database_manager, database_name, THREAT_BULK_UNUSED_A)
        _insert_threat(database_manager, database_name, THREAT_BULK_UNUSED_B)
        _insert_threat(database_manager, database_name, THREAT_BULK_USED)
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .insert_one({'public_id': BULK_RISK_ID, 'threats': [THREAT_BULK_USED], 'vulnerabilities': []})

        ids = f'{THREAT_BULK_UNUSED_A},{THREAT_BULK_UNUSED_B},{THREAT_BULK_USED}'
        response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        body = response.get_json()
        assert body['successfully'] == sorted([THREAT_BULK_UNUSED_A, THREAT_BULK_UNUSED_B])
        assert body['in_use'] == [THREAT_BULK_USED]
        assert rest_api.get(f'{ROUTE_URL}/{THREAT_BULK_UNUSED_A}').status_code == HTTPStatus.NOT_FOUND
        assert rest_api.get(f'{ROUTE_URL}/{THREAT_BULK_USED}').status_code == HTTPStatus.OK

    def test_bulk_delete_ignores_non_existent_ids(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A non-existent id is neither deleted-reported nor errored; only real deletions are listed."""
        _insert_threat(database_manager, database_name, THREAT_BULK_UNUSED_A)

        response = rest_api.delete(f'{ROUTE_URL}/delete/{THREAT_BULK_UNUSED_A},{MISSING_THREAT_ID}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        body = response.get_json()
        assert body['successfully'] == [THREAT_BULK_UNUSED_A]
        assert body['in_use'] == []

    def test_bulk_delete_invalid_id_returns_400(self, rest_api) -> None:
        """A non-integer id in the list is rejected with 400."""
        assert rest_api.delete(f'{ROUTE_URL}/delete/{THREAT_BULK_UNUSED_A},not-an-int')\
            .status_code == HTTPStatus.BAD_REQUEST


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ThreatManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ThreatManager, 'insert_item', _raiser(ThreatManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_threat_payload(THREAT_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ThreatManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ThreatManager, 'iterate_items', _raiser(ThreatManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ThreatManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ThreatManager, 'get_item', _raiser(ThreatManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{THREAT_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ThreatManagerUpdateError (threat found) surfaces as 400."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_UPDATE)
        monkeypatch.setattr(ThreatManager, 'update_item', _raiser(ThreatManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{THREAT_ID_FOR_UPDATE}',
                            json=_threat_payload(THREAT_ID_FOR_UPDATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ThreatManagerDeleteError (threat found) surfaces as 400."""
        _insert_threat(database_manager, database_name, THREAT_ID_FOR_DELETE)
        monkeypatch.setattr(ThreatManager, 'delete_with_follow_up', _raiser(ThreatManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{THREAT_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

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
Unit tests for subscription_license_helper - the hosted cloud's GET /license/current

Driven without HTTP: the portal client is patched. Pinned: what makes a portal answer unusable (its schema, another
database), the on-premise shape of the answer (``hmac`` null, the entitlement keys in their order, ``is_active`` and
``status`` from the validity window) and the statuses a failed read answers (502 for an error or unusable answer,
503 for an unreachable portal).
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from werkzeug.exceptions import HTTPException

from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import LicenseVerificationStatus
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    SERVICE_PORTAL_UNREACHABLE_MESSAGE,
    SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE,
    CurrentLicenseResponseKey,
)
from cmdb.interface.rest_api.routes.cmdb_license.subscription_license_helper import (
    build_subscription_license_payload,
    check_subscription_license,
    subscription_license_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.cmdb_license.subscription_license_helper'
DATABASE: str = 'db_acme'
OTHER_DATABASE: str = 'db_globex'
EMAIL: str = 'user@acme.com'
START_MS: int = 1767225600000
END_MS: int = 1798761599000
INSIDE_MS: int = START_MS + 1
BEFORE_MS: int = START_MS - 1
AFTER_MS: int = END_MS + 1
PORTAL_LICENSE: dict[str, Any] = {
    'databaseName': DATABASE, 'subId': 'SUB-2026-0042', 'licenseId': 'LIC-7f3a9c21', 'type': 'business',
    'features': ['rest_api', 'ipam', 'isms'], 'startDate': START_MS, 'endDate': END_MS,
}
ON_PREMISE_KEYS: list[str] = [*LicenseEntitlement.to_json(LicenseEntitlement.from_data({})), 'is_active', 'status']


def _license(**changes: Any) -> dict[str, Any]:
    """The portal license with some keys changed; a None value drops the key"""
    changed: dict[str, Any] = {**PORTAL_LICENSE, **changes}
    return {key: value for key, value in changed.items() if value is not None}


class TestCheckSubscriptionLicense:
    """What the route refuses to show"""

    def test_the_documented_answer_passes(self) -> None:
        """The portal team's example"""
        check_subscription_license(PORTAL_LICENSE, DATABASE)

    def test_without_database_name_passes(self) -> None:
        """The key is optional"""
        check_subscription_license(_license(databaseName=None), DATABASE)

    def test_unknown_keys_and_features_pass(self) -> None:
        """A plan name or feature the backend does not know is shown as sent"""
        check_subscription_license(_license(type='enterprise-cloud', features=['new_thing'], extra=1), DATABASE)

    @pytest.mark.parametrize('changes', [
        {'subId': None}, {'licenseId': None}, {'type': ''}, {'features': 'ipam'}, {'features': ['']},
        {'startDate': '2026-01-01'}, {'endDate': -1}, {'startDate': None},
    ], ids=['no-subId', 'no-licenseId', 'blank-type', 'features-not-a-list', 'blank-feature',
            'start-not-a-number', 'negative-end', 'no-start'])
    def test_a_license_off_its_schema_is_refused(self, changes: dict[str, Any]) -> None:
        """Named in the error"""
        with pytest.raises(DgServicePortalGetError, match='schema'):
            check_subscription_license(_license(**changes), DATABASE)

    def test_another_databases_license_is_refused(self) -> None:
        """Never another tenant's license"""
        with pytest.raises(DgServicePortalGetError, match=OTHER_DATABASE):
            check_subscription_license(_license(databaseName=OTHER_DATABASE), DATABASE)


class TestBuildSubscriptionLicensePayload:
    """The on-premise shape"""

    def test_the_keys_and_values_inside_the_window(self) -> None:
        """hmac null, the portal's values, active and valid"""
        payload: dict[str, Any] = build_subscription_license_payload(PORTAL_LICENSE, INSIDE_MS)

        assert list(payload) == ON_PREMISE_KEYS
        assert payload == {
            'hmac': None, 'startDate': START_MS, 'endDate': END_MS, 'subId': 'SUB-2026-0042',
            'licenseId': 'LIC-7f3a9c21', 'type': 'business', 'features': ['rest_api', 'ipam', 'isms'],
            'is_active': True, 'status': 'valid',
        }

    @pytest.mark.parametrize('now_ms, changes, active, status', [
        (BEFORE_MS, {}, False, LicenseVerificationStatus.NOT_YET_VALID),
        (AFTER_MS, {}, False, LicenseVerificationStatus.EXPIRED),
        (AFTER_MS, {'endDate': 0}, True, LicenseVerificationStatus.VALID),
    ], ids=['not-started', 'ended', 'no-expiry'])
    def test_the_window_decides_active_and_status(self, now_ms: int, changes: dict[str, Any], active: bool,
                                                  status: LicenseVerificationStatus) -> None:
        """Judged exactly as on premise"""
        payload: dict[str, Any] = build_subscription_license_payload(_license(**changes), now_ms)

        assert payload[CurrentLicenseResponseKey.IS_ACTIVE] is active
        assert payload[CurrentLicenseResponseKey.STATUS] == status.value

    def test_the_portals_feature_list_is_copied(self) -> None:
        """The answer never shares the portal's list"""
        portal_license: dict[str, Any] = _license(features=['ipam'])

        payload: dict[str, Any] = build_subscription_license_payload(portal_license, INSIDE_MS)
        payload['features'].append('isms')

        assert portal_license['features'] == ['ipam']


def _portal(answer: Any) -> MagicMock:
    """A patched portal client class whose license call answers ``answer`` (or raises it)"""
    portal_class = MagicMock()
    call = portal_class.return_value.get_subscription_license
    if isinstance(answer, Exception):
        call.side_effect = answer
    else:
        call.return_value = answer
    return portal_class


class TestSubscriptionLicensePayload:
    """The read the route makes"""

    def _run(self, answer: Any) -> tuple[MagicMock, Any]:
        """Runs the read for a user of the tenant, the portal answering ``answer``"""
        portal_class = _portal(answer)
        user = MagicMock(email=EMAIL)
        with patch(f'{PATH}.DgServicePortalManager', portal_class), \
             patch(f'{PATH}.ManagerProvider.tenant_database', return_value=DATABASE):
            return portal_class, subscription_license_payload(user, INSIDE_MS)

    def test_asks_for_the_users_email_and_tenant_database(self) -> None:
        """And builds the answer"""
        portal_class, payload = self._run(PORTAL_LICENSE)

        portal_class.return_value.get_subscription_license.assert_called_once_with(EMAIL, DATABASE)
        assert payload == build_subscription_license_payload(PORTAL_LICENSE, INSIDE_MS)

    @pytest.mark.parametrize('answer', [
        DgServicePortalGetError('status 500'), _license(subId=None), _license(databaseName=OTHER_DATABASE),
    ], ids=['error-status', 'off-schema', 'other-database'])
    def test_an_unusable_answer_is_a_502(self, answer: Any) -> None:
        """The gateway answered, but nothing showable"""
        with pytest.raises(HTTPException) as exc_info:
            self._run(answer)

        assert exc_info.value.code == HTTPStatus.BAD_GATEWAY
        assert exc_info.value.description == SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE

    @pytest.mark.parametrize('failure', [requests.ConnectionError('down'), requests.Timeout('slow')],
                             ids=['connection', 'timeout'])
    def test_an_unreachable_portal_is_a_503(self, failure: Exception) -> None:
        """No answer at all"""
        with pytest.raises(HTTPException) as exc_info:
            self._run(failure)

        assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert exc_info.value.description == SERVICE_PORTAL_UNREACHABLE_MESSAGE

    def test_a_bug_is_not_answered_here(self) -> None:
        """Only the portal's failures have a status of their own"""
        with pytest.raises(KeyError):
            self._run(KeyError('bug'))

    def test_without_a_moment_it_judges_now(self) -> None:
        """The clock is read when none is given"""
        user = MagicMock(email=EMAIL)
        with patch(f'{PATH}.DgServicePortalManager', _portal(_license(startDate=0, endDate=0))), \
             patch(f'{PATH}.ManagerProvider.tenant_database', return_value=DATABASE):
            payload: dict[str, Any] = subscription_license_payload(user)

        assert payload[CurrentLicenseResponseKey.STATUS] == LicenseVerificationStatus.VALID.value

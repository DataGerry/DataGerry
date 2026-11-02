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
Functional tests: the licence is resolved at most once per request, through the real REST app

Counted as reads of the stored licence (`ActiveLicenseManager.get_active_license_blob`, the first step of every
resolution) on a licensed install (verification patched to accept the stored blob,
as the licence route tests do - the shipped key's private half is not in CI): a Bearer request to an ungated route
resolves nothing, a Bearer request to a gated route once, and an HTTP Basic request to a gated route - which asks
about REST_API and the route's own feature - once as well. The routes that change the licence answer the NEW licence
even when a guard resolved the old one earlier in the same request (an HTTP Basic activate or delete)
"""
import base64
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager import license_service as svc_module
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import LicenseFeature, LicenseTier, LicenseVerificationStatus
from cmdb.security.license.verification import LicenseVerificationResult
from cmdb.interface.route_utils import BASIC_AUTH_HEADER_PREFIX
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATE_LICENSE_ROUTE,
    CURRENT_LICENSE_ROUTE,
    LicenseUploadKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

ACTIVATE_URL: str = f'/license{ACTIVATE_LICENSE_ROUTE}'
CURRENT_URL: str = f'/license{CURRENT_LICENSE_ROUTE}'
UNGATED_URL: str = '/objects/'
IPAM_GATED_URL: str = '/ports/interface_links/dangling'
BASIC: dict[str, str] = {
    'HTTP_AUTHORIZATION': BASIC_AUTH_HEADER_PREFIX + base64.b64encode(b'admin:admin').decode('utf-8'),
}
RESULT_KEY: str = 'result'
TYPE_KEY: str = 'type'
#: The stored licence unlocks everything; the one activated later is another tier, told apart by its blob
STORED_BLOB: str = 'stored-licence'
UPGRADE_BLOB: str = 'upgrade-licence'
BLOB_TIERS: dict[str, str] = {STORED_BLOB: LicenseTier.CORE.value, UPGRADE_BLOB: LicenseTier.BUSINESS.value}


@pytest.fixture(name='resolutions')
def fixture_resolutions(rest_api, database_manager: MongoDatabaseManager, database_name: str,
                        monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """A licensed install (every feature, the blob's own tier) and a count of the resolutions; removed afterwards"""
    def _verify(blob: str, *_args: object, **_kwargs: object) -> LicenseVerificationResult:
        entitlement = LicenseEntitlement(hmac='bind', license_type=BLOB_TIERS[blob],
                                         features=[feature.value for feature in LicenseFeature])
        return LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement)

    monkeypatch.setattr(svc_module, 'verify_license', _verify)
    assert rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: STORED_BLOB}).status_code == HTTPStatus.OK

    counted: list[int] = []
    real = ActiveLicenseManager.get_active_license_blob

    def _counting(self: ActiveLicenseManager) -> Any:
        counted.append(1)
        return real(self)

    monkeypatch.setattr(ActiveLicenseManager, 'get_active_license_blob', _counting)

    yield counted

    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


def _resolved_by(rest_api, resolutions: list[int], url: str, environ: dict[str, str] | None = None) -> int:
    """How many times one GET resolved the licence (it must answer 200)"""
    resolutions.clear()
    response = rest_api.get(url, environ_overrides=environ) if environ else rest_api.get(url)

    assert response.status_code == HTTPStatus.OK
    return len(resolutions)


class TestOnceAtMost:
    """However many features a request asks about, the licence is resolved once."""

    def test_an_ungated_bearer_request_resolves_nothing(self, rest_api, resolutions: list[int]) -> None:
        """Nothing asks"""
        assert _resolved_by(rest_api, resolutions, UNGATED_URL) == 0

    def test_a_gated_bearer_request_resolves_once(self, rest_api, resolutions: list[int]) -> None:
        """The route's own feature"""
        assert _resolved_by(rest_api, resolutions, IPAM_GATED_URL) == 1

    def test_a_basic_request_resolves_once(self, rest_api, resolutions: list[int]) -> None:
        """REST_API alone on an ungated route"""
        assert _resolved_by(rest_api, resolutions, UNGATED_URL, BASIC) == 1

    def test_a_gated_basic_request_resolves_once_for_both_features(self, rest_api, resolutions: list[int]) -> None:
        """REST_API and IPAM from one resolution - two until the state was kept per request"""
        assert _resolved_by(rest_api, resolutions, IPAM_GATED_URL, BASIC) == 1


@pytest.mark.usefixtures('resolutions')
class TestALicenceChangeIsAnsweredAsNew:
    """The REST_API guard resolved the old licence first - the answer still reads the new one."""

    def test_a_basic_activate_answers_the_activated_licence(self, rest_api) -> None:
        """The upgrade's tier, not the stored one the guard read"""
        response = rest_api.post(ACTIVATE_URL, json={LicenseUploadKey.BLOB.value: UPGRADE_BLOB},
                                 environ_overrides=BASIC)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[RESULT_KEY][TYPE_KEY] == LicenseTier.BUSINESS.value

    def test_a_basic_delete_answers_the_free_tier(self, rest_api) -> None:
        """The removed licence is not answered back"""
        response = rest_api.delete(CURRENT_URL, environ_overrides=BASIC)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[RESULT_KEY][TYPE_KEY] == LicenseTier.FREE.value

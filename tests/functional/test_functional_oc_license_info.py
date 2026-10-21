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
Functional tests: what ``GET /open_celium/licenses/info`` asks OpenCelium for, over HTTP

The route answers the active licence and one page of its usage in one body, so it costs two OpenCelium round trips,
one after the other - the licence first - inside one ``try``: a failing half fails the request. Only the HTTP layer of the connector is replaced, by a recorder answering per endpoint, so the
manager, the route and its error tail run for real
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.open_celium_managers.oc_license_manager import ACTIVE_LICENSE_URL, LICENSE_USAGE_URL
from cmdb.open_celium.oc_api_connector import OcApiConnector
from cmdb.open_celium.oc_constants import OC_CONFIG_BASE_URL_KEY, OcConfigKey
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

INFO_URL: str = '/open_celium/licenses/info'

STUB_OC_CONFIG: dict[str, Any] = {
    OcConfigKey.HOST: 'oc.invalid', OcConfigKey.PORT: 1, OcConfigKey.PROTOCOL: 'http',
    OcConfigKey.EMAIL: 'oc@x.io', OcConfigKey.USER: 'oc', OcConfigKey.PASSWORD: 'pw',
    OC_CONFIG_BASE_URL_KEY: 'http://oc.invalid:1',
}

ACTIVE_LICENSE: dict[str, Any] = {'id': 'license-1', 'status': 'ACTIVE'}
USAGE_PAGE: dict[str, Any] = {'content': [{'operation': 'sync', 'count': 3}], 'totalElements': 1}

OK: int = 200
OC_FAILURE: int = 500


class _RecordingOpenCelium:
    """Answers each OpenCelium GET by its endpoint and records the endpoints asked, in order."""

    def __init__(self, failing: str | None = None) -> None:
        self.asked: list[str] = []
        self._failing: str | None = failing

    def oc_get(self, _connector: Any, endpoint: str, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        """The stand-in for `OcApiConnector.oc_get`."""
        self.asked.append(endpoint)

        if self._failing and endpoint.startswith(self._failing):
            return SimpleNamespace(status_code=OC_FAILURE, text='down')

        body: dict[str, Any] = ACTIVE_LICENSE if endpoint.startswith(ACTIVE_LICENSE_URL) else USAGE_PAGE

        return SimpleNamespace(status_code=OK, text=json.dumps(body))


@pytest.fixture(name='open_celium')
def fixture_open_celium(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The licensed automations surface talking to the recorder; yields a factory choosing what fails."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)
    monkeypatch.setattr(OcApiConnector, '_load_local_config', staticmethod(lambda: STUB_OC_CONFIG))

    def _install(failing: str | None = None) -> _RecordingOpenCelium:
        recorder = _RecordingOpenCelium(failing)
        monkeypatch.setattr(OcApiConnector, 'oc_get',
                            lambda connector, endpoint, *args, **kwargs: recorder.oc_get(connector, endpoint))

        return recorder

    return _install


class TestTwoRoundTrips:
    """One request, two OpenCelium calls, the licence first."""

    def test_both_halves_come_back_in_one_body(self, rest_api, open_celium) -> None:
        """What the frontend's LicenseInfoResponse reads"""
        open_celium()

        response = rest_api.get(f'{INFO_URL}?page=0&size=5')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'license': ACTIVE_LICENSE, 'usage': USAGE_PAGE}

    def test_exactly_two_calls_licence_first_then_the_requested_page(self, rest_api, open_celium) -> None:
        """The frontend's request: page 0, size 5 - forwarded as sent"""
        recorder: _RecordingOpenCelium = open_celium()

        rest_api.get(f'{INFO_URL}?page=0&size=5')

        assert len(recorder.asked) == 2
        assert recorder.asked[0] == ACTIVE_LICENSE_URL
        usage_path, _, usage_query = recorder.asked[1].partition('?')
        assert usage_path == LICENSE_USAGE_URL
        # the month window rides along; the paging is the caller's, as sent
        assert {key: values[0] for key, values in parse_qs(usage_query).items()
                if key in ('page', 'size')} == {'page': '0', 'size': '5'}


class TestOneFailingHalfFailsTheRequest:
    """The two calls share one try - no half answer."""

    def test_a_failing_usage_read_costs_the_licence_half_too(self, rest_api, open_celium) -> None:
        """The licence was read, and is still not answered"""
        recorder: _RecordingOpenCelium = open_celium(failing=LICENSE_USAGE_URL)

        response = rest_api.get(INFO_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == 'Failed to retrieve OpenCelium License info!'
        assert recorder.asked[0] == ACTIVE_LICENSE_URL

    def test_a_failing_licence_read_never_asks_for_the_usage(self, rest_api, open_celium) -> None:
        """Sequential: the second call is not made after the first failed"""
        recorder: _RecordingOpenCelium = open_celium(failing=ACTIVE_LICENSE_URL)

        response = rest_api.get(INFO_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert recorder.asked == [ACTIVE_LICENSE_URL]

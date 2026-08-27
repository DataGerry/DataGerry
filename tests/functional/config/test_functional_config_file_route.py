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
Functional smoke for the ``/config_file/status/opencelium`` REST route

Exercises the route over HTTP with the Automations feature licensed, so the blueprint gate lets the
request through and the route's own answer is what is asserted. The config reader is stubbed at the
route module path: the test harness runs config-less, and the point here is the response contract
the Angular Automations view depends on, not which file the process happens to have loaded.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

CONFIG_ROUTES: str = 'cmdb.interface.rest_api.routes.config_routes.config_file_routes'
STATUS_URL: str = '/config_file/status/opencelium'

SETTING_KEYS: tuple[str, ...] = ('host', 'port', 'protocol', 'email', 'user', 'password')
RESPONSE_KEYS: tuple[str, ...] = ('status', 'section') + SETTING_KEYS

COMPLETE_SECTION: dict[str, Any] = {
    'host': '127.0.0.1',
    'port': 9090,
    'protocol': 'http',
    'email': 'oc@example.com',
    'user': 'oc-user',
    'password': 'oc-password',
}


@pytest.fixture(autouse=True)
def _automations_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the Automations feature so the blueprint gate does not answer 403 first"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.AUTOMATIONS,
    )


def _stub_section(monkeypatch: pytest.MonkeyPatch, section_values: dict[str, Any] | Exception) -> None:
    """Points the route's config reader at a fixed section (or makes it raise)"""
    class _Reader:
        """Stand-in for the process-wide ConfigFileReader"""
        def get_all_values_from_section(self, _section: str) -> dict[str, Any]:
            """Returns the prepared section values, or raises the prepared error"""
            if isinstance(section_values, Exception):
                raise section_values

            return section_values

    monkeypatch.setattr(f'{CONFIG_ROUTES}.SystemConfigReader', lambda *_args, **_kwargs: _Reader())


class TestOpenCeliumConfigStatus:
    """GET /config_file/status/opencelium reports which [OpenCelium] settings are configured."""

    def test_complete_section_reports_ready(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A fully configured section answers 200 with every flag - and the overall status - True."""
        _stub_section(monkeypatch, COMPLETE_SECTION)

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'status': True, 'section': True, **{key: True for key in SETTING_KEYS}}

    def test_response_carries_the_full_frontend_contract(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every key the Angular OpenCeliumConfigStatus type declares is present and a bool."""
        _stub_section(monkeypatch, COMPLETE_SECTION)

        body = rest_api.get(STATUS_URL).get_json()

        assert set(body) == set(RESPONSE_KEYS)
        assert all(isinstance(body[key], bool) for key in RESPONSE_KEYS)

    def test_partial_section_answers_200_with_flags(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """A half-filled section is reported per setting instead of failing the request with a 500."""
        _stub_section(monkeypatch, {'host': '127.0.0.1', 'port': 9090, 'protocol': 'http'})

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {
            'status': False,
            'section': True,
            'host': True,
            'port': True,
            'protocol': True,
            'email': False,
            'user': False,
            'password': False,
        }

    def test_missing_section_reports_section_false(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """An absent [OpenCelium] block answers 200 with section=False and every flag False."""
        _stub_section(monkeypatch, SectionError('The section does not exist!'))

        response = rest_api.get(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'status': False, 'section': False, **{key: False for key in SETTING_KEYS}}

    def test_reader_failure_returns_500(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unexpected reader failure is reported as 500."""
        _stub_section(monkeypatch, RuntimeError('boom'))

        assert rest_api.get(STATUS_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_requires_authentication(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without an Authorization header the route answers 401, not the config status."""
        _stub_section(monkeypatch, COMPLETE_SECTION)

        response = rest_api.get(STATUS_URL, unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED

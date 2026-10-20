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

Exercises the route over HTTP with the Automations feature licensed, so the route's licence gate lets the
request through and the route's own answer is what is asserted. The config reader is stubbed at the
route module path: the test harness runs config-less, and the point here is the response contract
the Angular Automations view depends on, not which file the process happens to have loaded. The route asks for
``base.openCelium.connection.view``: the seeded user group is refused, that right alone is enough.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import USER_GROUP_ID, CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcRight
from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

CONFIG_ROUTES: str = 'cmdb.interface.rest_api.routes.config_routes.config_file_routes'
STATUS_URL: str = '/config_file/status/opencelium'

READ_ONLY_USER_ID: int = 97801
CONNECTION_VIEWER_GROUP_ID: int = 97811

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

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
    """Licenses the Automations feature so the route's licence gate does not answer 403 first"""
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

    def test_head_answers_200_without_a_body(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """HEAD is registered beside GET: the same status, no body."""
        _stub_section(monkeypatch, COMPLETE_SECTION)

        response = rest_api.head(STATUS_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_data() == b''

    @pytest.mark.parametrize('group_id, expected', [
        (USER_GROUP_ID, HTTPStatus.FORBIDDEN),
        (CONNECTION_VIEWER_GROUP_ID, HTTPStatus.OK),
    ], ids=['default-user-group', 'connection-view-alone'])
    def test_the_route_asks_for_the_connection_view_right(self, rest_api, monkeypatch: pytest.MonkeyPatch,
                                                          database_manager: MongoDatabaseManager, database_name: str,
                                                          group_id: int, expected: HTTPStatus) -> None:
        """base.openCelium.connection.view - the right the automations list, its one reader, is guarded by"""
        _stub_section(monkeypatch, COMPLETE_SECTION)
        groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        groups.delete_many({'public_id': CONNECTION_VIEWER_GROUP_ID})
        users.delete_many({'public_id': READ_ONLY_USER_ID})
        groups.insert_one({'public_id': CONNECTION_VIEWER_GROUP_ID, 'name': 'config-oc-viewers', 'label': 'OC',
                           'rights': [OcRight.CONNECTION_VIEW.value]})
        users.insert_one({'public_id': READ_ONLY_USER_ID, 'user_name': f'config-reader-{READ_ONLY_USER_ID}',
                          'active': True, 'group_id': group_id, 'password': 'stub', 'api_level': 0,
                          'authenticator': 'LocalAuthenticationProvider', 'database': database_name})

        try:
            response = rest_api.get(STATUS_URL, user=CmdbUser(public_id=READ_ONLY_USER_ID,
                                                              user_name=f'config-reader-{READ_ONLY_USER_ID}',
                                                              active=True, group_id=group_id))
        finally:
            users.delete_many({'public_id': READ_ONLY_USER_ID})
            groups.delete_many({'public_id': CONNECTION_VIEWER_GROUP_ID})

        assert response.status_code == expected

        if expected == HTTPStatus.FORBIDDEN:
            assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=OcRight.CONNECTION_VIEW.value)
            assert 'password' not in response.get_data(as_text=True)
        else:
            assert response.get_json()['status'] is True

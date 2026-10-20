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
Functional tests: the ``?opsIncluded=`` flag of ``GET /open_celium/invokers`` over HTTP

The flag follows the API's one rule for boolean query parameters: absent means the operations are included, ``true``
/ ``false`` set it, anything else - the empty value included - is a 400 before OpenCelium is asked anything. The
manager is replaced by a recorder at the route module, so the tests see exactly what the route asked for
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.open_celium_routes import oc_invoker_routes
from cmdb.open_celium.oc_constants import OC_OPS_INCLUDED_PARAM
# -------------------------------------------------------------------------------------------------------------------- #

INVOKERS_URL: str = '/open_celium/invokers'


@pytest.fixture(name='invoker_manager')
def fixture_invoker_manager(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The licensed automations surface, with the invoker manager replaced by a recorder."""
    manager = MagicMock(name='oc_invoker_manager')
    manager.get_all_invokers.return_value = []

    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)
    monkeypatch.setattr(oc_invoker_routes, 'build_invoker_manager', lambda _request_user: manager)

    return manager


def _get(rest_api, query: str = '') -> Any:
    """GET the invoker list with the given query string."""
    return rest_api.get(f'{INVOKERS_URL}{query}')


class TestTheFlag:
    """What the route asks OpenCelium for, by spelling."""

    def test_absent_asks_for_the_operations(self, rest_api, invoker_manager: MagicMock) -> None:
        """The frontend sends no parameter - the default"""
        assert _get(rest_api).status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(True)

    @pytest.mark.parametrize('value, expected', [('false', False), ('FALSE', False), ('true', True)])
    def test_true_and_false_are_honoured(self, rest_api, invoker_manager: MagicMock, value: str,
                                         expected: bool) -> None:
        """Any casing"""
        assert _get(rest_api, f'?{OC_OPS_INCLUDED_PARAM}={value}').status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(expected)

    @pytest.mark.parametrize('value', ['', '0', 'no', 'off'], ids=['empty', 'zero', 'no', 'off'])
    def test_any_other_value_is_a_400_before_opencelium_is_asked(
            self, rest_api, invoker_manager: MagicMock, value: str) -> None:
        """Refused, naming the parameter - and nothing is sent to OpenCelium"""
        response = _get(rest_api, f'?{OC_OPS_INCLUDED_PARAM}={value}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert OC_OPS_INCLUDED_PARAM in response.get_json()['message']
        invoker_manager.get_all_invokers.assert_not_called()

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
Functional tests: what an OpenCelium route answers when the way to OpenCelium fails, over HTTP

``handle_oc_errors`` sits outermost on every OpenCelium route. The invoker list stands in for all of them: its manager
is replaced by one that raises what ``requests`` would, and the answer is checked in full - always a 500, the message
naming what kind of failure it was. A stored OpenCelium URL without a scheme raises ``MissingSchema``, which used to
fall through to the generic message. A lost database connection or a lock timeout is not OpenCelium's: it passes
through to the app's error handlers - 503 / 423, as on every other route - where it used to become the generic 500
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from requests import exceptions as requests_errors

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface import route_utils
from cmdb.interface.rest_api.routes.open_celium_routes import oc_invoker_routes
from cmdb.errors.open_celium import AuthError
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.interface.rest_api.responses.error_handlers import DATABASE_LOCKED_MSG, DATABASE_UNAVAILABLE_MSG
# -------------------------------------------------------------------------------------------------------------------- #

INVOKERS_URL: str = '/open_celium/invokers'


def _failing_route(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """The licensed automations surface, with the invoker manager raising the given failure"""
    manager = MagicMock(name='oc_invoker_manager')
    manager.get_all_invokers.side_effect = failure

    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)
    monkeypatch.setattr(oc_invoker_routes, 'build_invoker_manager', lambda _request_user: manager)


@pytest.mark.parametrize('failure, message', [
    (AuthError('refused'), route_utils.OC_AUTH_FAILED_MESSAGE),
    (requests_errors.ConnectTimeout('no answer'), route_utils.OC_CONNECT_TIMEOUT_MESSAGE),
    (requests_errors.ConnectionError('refused'), route_utils.OC_CONNECTION_FAILED_MESSAGE),
    (requests_errors.ReadTimeout('slow'), route_utils.OC_TIMEOUT_MESSAGE),
    (requests_errors.MissingSchema('no scheme'), route_utils.OC_REQUEST_FAILED_MESSAGE),
    (requests_errors.InvalidURL('bad url'), route_utils.OC_REQUEST_FAILED_MESSAGE),
], ids=['auth', 'connect-timeout', 'connection', 'read-timeout', 'missing-schema', 'invalid-url'])
def test_each_failure_answers_a_500_naming_its_kind(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                     failure: Exception, message: str) -> None:
    """The message the automations screen shows as its toast"""
    _failing_route(monkeypatch, failure)

    response = rest_api.get(INVOKERS_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] == message


def test_a_url_without_a_scheme_no_longer_answers_the_generic_message(rest_api,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """A misconfigured OpenCelium URL is told apart from a bug in DataGerry"""
    _failing_route(monkeypatch, requests_errors.MissingSchema('oc.example.com'))

    message: str = rest_api.get(INVOKERS_URL).get_json()['message']

    assert not message.startswith(route_utils.OC_GENERIC_ERROR_MESSAGE.rstrip('!'))


@pytest.mark.parametrize('failure, status, message', [
    (DocumentNetworkError('lost'), HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
    (DocumentLockTimeoutError('locked'), HTTPStatus.LOCKED, DATABASE_LOCKED_MSG),
], ids=['network', 'lock'])
def test_a_database_outage_answers_as_on_every_other_route(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                           failure: Exception, status: HTTPStatus,
                                                           message: str) -> None:
    """The app's 503 / 423 with its own message, not the OpenCelium decorator's generic 500"""
    _failing_route(monkeypatch, failure)

    response = rest_api.get(INVOKERS_URL)

    assert response.status_code == status
    assert response.get_json()['message'] == message

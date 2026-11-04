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
Unit tests for subscription_license_helper - the hosted cloud's GET /license/subscription

Driven without HTTP: the portal client is patched. Pinned: the user's email and tenant database are asked for, the
portal's answer is forwarded unchanged (``trial`` and keys the backend does not know included, nothing checked or
added) and the statuses a failed read answers (502 for an error answer, 503 for an unreachable portal).
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from werkzeug.exceptions import HTTPException

from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    SERVICE_PORTAL_UNREACHABLE_MESSAGE,
    SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE,
)
from cmdb.interface.rest_api.routes.cmdb_license.subscription_license_helper import subscription_license_payload
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.cmdb_license.subscription_license_helper'
DATABASE: str = 'db_acme'
EMAIL: str = 'user@acme.com'
PORTAL_LICENSE: dict[str, Any] = {
    'databaseName': DATABASE, 'subId': 'SUB-2026-0042', 'licenseId': 'LIC-7f3a9c21', 'type': 'business',
    'features': ['rest_api', 'ipam', 'isms'], 'startDate': 1767225600000, 'endDate': 1798761599000, 'trial': True,
}
# What the old checks refused: no ids, a features string, a negative end, another tenant's database, a new key
UNCHECKED_LICENSE: dict[str, Any] = {
    'databaseName': 'db_globex', 'type': '', 'features': 'ipam', 'endDate': -1, 'trial': False, 'extra': 1,
}


def _portal(answer: Any) -> MagicMock:
    """A patched portal client class whose license call answers ``answer`` (or raises it)"""
    portal_class = MagicMock()
    call = portal_class.return_value.get_subscription_license
    if isinstance(answer, Exception):
        call.side_effect = answer
    else:
        call.return_value = answer
    return portal_class


def _run(answer: Any) -> tuple[MagicMock, Any]:
    """Runs the read for a user of the tenant, the portal answering ``answer``"""
    portal_class = _portal(answer)
    user = MagicMock(email=EMAIL)
    with patch(f'{PATH}.DgServicePortalManager', portal_class), \
         patch(f'{PATH}.ManagerProvider.tenant_database', return_value=DATABASE):
        return portal_class, subscription_license_payload(user)


def test_asks_for_the_users_email_and_tenant_database() -> None:
    """Once per read"""
    portal_class, _payload = _run(PORTAL_LICENSE)

    portal_class.return_value.get_subscription_license.assert_called_once_with(EMAIL, DATABASE)


@pytest.mark.parametrize('answer', [PORTAL_LICENSE, UNCHECKED_LICENSE, {}], ids=['documented', 'unchecked', 'empty'])
def test_the_answer_is_forwarded_unchanged(answer: dict[str, Any]) -> None:
    """Nothing checked, nothing added, nothing dropped"""
    _portal_class, payload = _run(answer)

    assert payload == answer
    assert list(payload) == list(answer)


def test_an_error_answer_is_a_502() -> None:
    """The gateway answered, but no license"""
    with pytest.raises(HTTPException) as exc_info:
        _run(DgServicePortalGetError('status 500'))

    assert exc_info.value.code == HTTPStatus.BAD_GATEWAY
    assert exc_info.value.description == SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE


@pytest.mark.parametrize('failure', [requests.ConnectionError('down'), requests.Timeout('slow')],
                         ids=['connection', 'timeout'])
def test_an_unreachable_portal_is_a_503(failure: Exception) -> None:
    """No answer at all"""
    with pytest.raises(HTTPException) as exc_info:
        _run(failure)

    assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert exc_info.value.description == SERVICE_PORTAL_UNREACHABLE_MESSAGE


def test_a_bug_is_not_answered_here() -> None:
    """Only the portal's failures have a status of their own"""
    with pytest.raises(KeyError):
        _run(KeyError('bug'))

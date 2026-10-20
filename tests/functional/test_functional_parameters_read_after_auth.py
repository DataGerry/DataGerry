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
Functional coverage that a route refuses the caller before it reads the caller's parameters

Five listing routes used to parse their collection parameters before authenticating or authorizing,
so a malformed ``filter`` was answered with the parser's own error text. Driven here with exactly that
request: a stranger now gets 401, a user without the route's right 403 - and a caller who may use the
route still gets the 400 for garbage. The IPAM-gated routes are licensed for the test, because their
blueprint's licence gate runs right after authentication - before the right and the parameters
"""
from datetime import datetime, timezone
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.manager.license_manager.license_service import LicenseService
# -------------------------------------------------------------------------------------------------------------------- #

MALFORMED_FILTER: str = '?filter=not-json'

# Each listing route that reads collection parameters, with a path that reaches the handler
LISTING_ROUTES: list[str] = [
    '/objects/',
    '/objects/references/1',
    '/port_connections/cables/unassigned/',
    '/racks/1/assignable_objects/',
    '/ci_explorer/profile',
]

NO_RIGHTS_GROUP_ID: int = 93810
NO_RIGHTS_USER_ID: int = 93811


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses every feature, so the IPAM-gated blueprints let the request reach the handler."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='rightless_user')
def fixture_rightless_user(database_manager: MongoDatabaseManager, database_name: str):
    """An authenticated user whose group holds no right at all."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups.delete_many({'public_id': NO_RIGHTS_GROUP_ID})
    users.delete_many({'public_id': NO_RIGHTS_USER_ID})
    groups.insert_one({'public_id': NO_RIGHTS_GROUP_ID, 'name': 'no-rights', 'label': 'No Rights', 'rights': []})
    users.insert_one({'public_id': NO_RIGHTS_USER_ID, 'user_name': 'no-rights-user', 'active': True,
                      'group_id': NO_RIGHTS_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=NO_RIGHTS_USER_ID, user_name='no-rights-user', active=True, group_id=NO_RIGHTS_GROUP_ID)

    users.delete_many({'public_id': NO_RIGHTS_USER_ID})
    groups.delete_many({'public_id': NO_RIGHTS_GROUP_ID})


@pytest.mark.parametrize('url', LISTING_ROUTES)
def test_a_stranger_is_refused_before_the_parameters_are_read(rest_api, url: str) -> None:
    """No token: 401, and the parser's error text never reaches the caller"""
    response = rest_api.get(f'{url}{MALFORMED_FILTER}', unauthorized=True)

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize('url', LISTING_ROUTES)
def test_a_user_without_the_right_is_refused_before_the_parameters_are_read(rest_api, rightless_user,
                                                                            url: str) -> None:
    """Authenticated but not authorized: 403, whatever the parameters say"""
    response = rest_api.get(f'{url}{MALFORMED_FILTER}', user=rightless_user)

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', LISTING_ROUTES)
def test_a_permitted_caller_still_gets_the_400_for_garbage(rest_api, url: str) -> None:
    """The parsing did not go away - it runs after the caller is known"""
    response = rest_api.get(f'{url}{MALFORMED_FILTER}')

    assert response.status_code == HTTPStatus.BAD_REQUEST

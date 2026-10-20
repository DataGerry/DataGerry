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
Functional census of the rights the OpenCelium Automation routes ask for

An Automation is a connection and its scheduler, so the scheduler, execution-log and template routes ask for the
connection right of the same operation, the invoker routes for the connector view right and OpenCelium's own
licence routes for the connection view right - the rights the frontend's automation screens are guarded by.
For every one of the 23 routes, pinned on a licensed installation:

  - a group without the right is a 403 naming it, before anything reaches OpenCelium
  - a group holding exactly that right gets past the gate (whatever OpenCelium then answers)
  - the Automation create and delete - which create and delete the connection too - need the connection add /
    delete right, so they no longer go around the connection routes' own gate

Besides, the scheduler update reads its body: anything but an object, or a blank title, is a 400.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.open_celium_routes import oc_scheduler_routes
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcAutomationMessage, OcRight
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

BASE: str = '/open_celium'
SCHEDULER_ID: int = 7
LOG_TARGET: int = 11

ROUTES: list[tuple[str, str, OcRight]] = [
    ('POST', f'{BASE}/schedulers', OcRight.CONNECTION_ADD),
    ('GET', f'{BASE}/schedulers/{SCHEDULER_ID}', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/schedulers', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/schedulers/running', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/schedulers/logs', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/schedulers/execute/{SCHEDULER_ID}', OcRight.CONNECTION_EDIT),
    ('PUT', f'{BASE}/schedulers/{SCHEDULER_ID}', OcRight.CONNECTION_EDIT),
    ('DELETE', f'{BASE}/schedulers/{SCHEDULER_ID}', OcRight.CONNECTION_DELETE),
    ('GET', f'{BASE}/connections/logs/node-1', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/connections/logs/children/node-1', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/connections/logs/flowcharts/{LOG_TARGET}', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/connections/logs/first_level/node-1', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/connections/logs/list', OcRight.CONNECTION_VIEW),
    ('DELETE', f'{BASE}/connections/logs/{LOG_TARGET}', OcRight.CONNECTION_DELETE),
    ('POST', f'{BASE}/templates', OcRight.CONNECTION_ADD),
    ('GET', f'{BASE}/templates/template-1', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/templates', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/templates/all/1/2', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/invokers', OcRight.CONNECTOR_VIEW),
    ('GET', f'{BASE}/invokers/DataGerry', OcRight.CONNECTOR_VIEW),
    ('GET', f'{BASE}/invokers/exists/DataGerry', OcRight.CONNECTOR_VIEW),
    ('GET', f'{BASE}/licenses/activation/generate', OcRight.CONNECTION_VIEW),
    ('GET', f'{BASE}/licenses/info', OcRight.CONNECTION_VIEW),
]
ROUTE_IDS: list[str] = [f'{method} {url.removeprefix(BASE)}' for method, url, _right in ROUTES]

RIGHTLESS_GROUP_ID: int = 88601
RIGHTLESS_USER_ID: int = 88611
# One group per right, holding exactly that right
RIGHT_GROUP_IDS: dict[OcRight, int] = {right: 88620 + index for index, right in enumerate(OcRight)}
RIGHT_USER_IDS: dict[OcRight, int] = {right: 88640 + index for index, right in enumerate(OcRight)}


@pytest.fixture(autouse=True)
def _automations_licensed(monkeypatch: pytest.MonkeyPatch):
    """The Automations licence, so the rights are what decides"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)


def _user(user_id: int, group_id: int) -> CmdbUser:
    """The model the test client sends as"""
    return CmdbUser(public_id=user_id, user_name=f'oc-rights-{user_id}', active=True, group_id=group_id)


@pytest.fixture(name='users', scope='module')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A user whose group holds no right, and one user per OpenCelium right holding exactly it"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    group_ids: list[int] = [RIGHTLESS_GROUP_ID, *RIGHT_GROUP_IDS.values()]
    user_ids: list[int] = [RIGHTLESS_USER_ID, *RIGHT_USER_IDS.values()]

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': group_ids}})
        users.delete_many({'public_id': {'$in': user_ids}})

    _purge()
    groups.insert_one({'public_id': RIGHTLESS_GROUP_ID, 'name': 'oc-rights-none', 'label': 'None', 'rights': []})
    groups.insert_many([{'public_id': group_id, 'name': f'oc-rights-{group_id}', 'label': right.value,
                         'rights': [right.value]} for right, group_id in RIGHT_GROUP_IDS.items()])
    users.insert_many([{'public_id': user_id, 'user_name': f'oc-rights-{user_id}', 'active': True,
                        'group_id': group_id, 'registration_time': datetime.now(timezone.utc)}
                       for user_id, group_id in zip(user_ids, group_ids)])
    yield {
        'rightless': _user(RIGHTLESS_USER_ID, RIGHTLESS_GROUP_ID),
        **{right: _user(RIGHT_USER_IDS[right], RIGHT_GROUP_IDS[right]) for right in OcRight},
    }
    _purge()


def _call(rest_api: Any, method: str, url: str, user: CmdbUser) -> Any:
    """Sends the request as ``user``; writes carry an empty object"""
    kwargs: dict[str, Any] = {'user': user}

    if method in ('POST', 'PUT'):
        kwargs['json'] = {}

    return getattr(rest_api, method.lower())(url, **kwargs)


@pytest.mark.parametrize('method, url, right', ROUTES, ids=ROUTE_IDS)
def test_without_the_right_the_route_is_a_403_naming_it(rest_api, users: dict[Any, CmdbUser], method: str, url: str,
                                                        right: OcRight) -> None:
    """Refused before anything reaches OpenCelium"""
    response = _call(rest_api, method, url, users['rightless'])

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=right.value)


@pytest.mark.parametrize('method, url, right', ROUTES, ids=ROUTE_IDS)
def test_the_right_alone_passes_the_gate(rest_api, users: dict[Any, CmdbUser], method: str, url: str,
                                         right: OcRight) -> None:
    """No other right is needed - what OpenCelium answers next is not this test's concern"""
    response = _call(rest_api, method, url, users[right])

    assert response.status_code != HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('method, url, right', [
    ('POST', f'{BASE}/schedulers', OcRight.CONNECTION_ADD),
    ('DELETE', f'{BASE}/schedulers/{SCHEDULER_ID}', OcRight.CONNECTION_DELETE),
], ids=['create', 'delete'])
def test_an_automation_write_needs_the_connection_right_it_writes_with(
        rest_api, users: dict[Any, CmdbUser], method: str, url: str, right: OcRight) -> None:
    """The view right is not enough to create or delete the connection an Automation carries"""
    response = _call(rest_api, method, url, users[OcRight.CONNECTION_VIEW])

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=right.value)

# --------------------------------------------------- update body ---------------------------------------------------- #

@pytest.mark.parametrize('body, message', [
    ([], OcAutomationMessage.UPDATE_BODY_NOT_AN_OBJECT),
    ('text', OcAutomationMessage.UPDATE_BODY_NOT_AN_OBJECT),
    ({'title': '   '}, OcAutomationMessage.UPDATE_TITLE_INVALID),
    ({'title': 5}, OcAutomationMessage.UPDATE_TITLE_INVALID),
], ids=['list', 'string', 'blank-title', 'number-title'])
def test_an_unusable_update_body_is_a_400(rest_api, monkeypatch, body: Any, message: OcAutomationMessage) -> None:
    """Refused before OpenCelium is asked; it used to fail with a 500 in the title mapping"""
    manager = MagicMock()
    monkeypatch.setattr(oc_scheduler_routes, 'build_scheduler_manager', lambda _user: manager)

    response = rest_api.put(f'{BASE}/schedulers/{SCHEDULER_ID}', json=body)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == message.value
    manager.update_scheduler.assert_not_called()


def test_a_usable_update_body_is_forwarded(rest_api, monkeypatch) -> None:
    """On premise the title is optional; the body reaches OpenCelium as sent"""
    manager = MagicMock()
    manager.update_scheduler.return_value = {'schedulerId': SCHEDULER_ID}
    monkeypatch.setattr(oc_scheduler_routes, 'build_scheduler_manager', lambda _user: manager)
    body: dict[str, Any] = {'cronExp': '0 0 * * * ?'}

    response = rest_api.put(f'{BASE}/schedulers/{SCHEDULER_ID}', json=body)

    assert response.status_code == HTTPStatus.OK
    manager.update_scheduler.assert_called_once_with(body, SCHEDULER_ID)

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
Unit tests for what an Automation delete does once its scheduler is gone (``oc_scheduler_helper``)

``run_remote_delete`` turns a refused or unreachable remote delete into False (a bug still raises);
``delete_automation_follow_ups`` attempts every step whatever the one before answered, removes the portal's
connectionId only once OpenCelium deleted the connection, evicts the user cache in any case, and names what it left
behind. Both services are mocks; there is no OpenCelium to test against.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from requests import exceptions as requests_errors

from cmdb.errors.open_celium import AuthError
from cmdb.interface.rest_api.routes.open_celium_routes import oc_scheduler_helper as helper
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import (
    OPEN_CELIUM_SERVICE,
    SERVICE_PORTAL,
    REMOTE_OBJECT,
)
# -------------------------------------------------------------------------------------------------------------------- #

SCHEDULER_ID: int = 5
CONNECTION_ID: int = 12
USER: SimpleNamespace = SimpleNamespace(email='user@test.com', database='tenant_db')
SERVICE: str = 'Remote'
DESCRIPTION: str = 'thing 1'
CONNECTION_LEFT: str = REMOTE_OBJECT.format(description=f'connection {CONNECTION_ID}', service=OPEN_CELIUM_SERVICE)
SCHEDULER_ID_LEFT: str = REMOTE_OBJECT.format(description=f'schedulerId {SCHEDULER_ID}', service=SERVICE_PORTAL)
CONNECTION_ID_LEFT: str = REMOTE_OBJECT.format(description=f'connectionId {CONNECTION_ID}', service=SERVICE_PORTAL)
OUTAGES: list[Exception] = [requests_errors.ConnectionError('down'), requests_errors.Timeout('slow'),
                            AuthError('login')]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  run_remote_delete                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_acknowledged_delete_is_true() -> None:
    """The service answered True"""
    assert helper.run_remote_delete(SERVICE, DESCRIPTION, lambda: True) is True


def test_a_refused_delete_is_false_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """The service answered False - nothing raised"""
    assert helper.run_remote_delete(SERVICE, DESCRIPTION, lambda: False) is False
    assert f'{SERVICE} refused to delete {DESCRIPTION}' in caplog.text


@pytest.mark.parametrize('error', OUTAGES, ids=['connection', 'timeout', 'auth'])
def test_an_unreachable_service_is_false_and_logged(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    """An outage after the Automation is gone must not end the request"""
    def delete() -> bool:
        raise error

    assert helper.run_remote_delete(SERVICE, DESCRIPTION, delete) is False
    assert DESCRIPTION in caplog.text


def test_a_bug_still_raises() -> None:
    """Only the service's own failures are caught"""
    def delete() -> bool:
        raise TypeError('bug')

    with pytest.raises(TypeError):
        helper.run_remote_delete(SERVICE, DESCRIPTION, delete)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             delete_automation_follow_ups                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def _services(scheduler_id: Any = True, connection: Any = True, connection_id: Any = True) -> SimpleNamespace:
    """The three services; each value is what its delete answers, or an exception it raises"""
    def answer(value: Any) -> dict[str, Any]:
        return {'side_effect': value} if isinstance(value, Exception) else {'return_value': value}

    portal = MagicMock(name='portal')
    portal.delete_scheduler_id.configure_mock(**answer(scheduler_id))
    portal.delete_connection_id.configure_mock(**answer(connection_id))
    connections = MagicMock(name='connections')
    connections.delete_connection.configure_mock(**answer(connection))

    return SimpleNamespace(portal=portal, connections=connections, cache=MagicMock(name='cache'))


def _follow_ups(services: SimpleNamespace, hosted: bool) -> list[str]:
    """Runs the follow-ups on or off the hosted cloud"""
    with patch.object(helper, 'is_hosted_cloud', return_value=hosted):
        return helper.delete_automation_follow_ups(
            USER, SCHEDULER_ID, CONNECTION_ID, services.connections,
            services.portal if hosted else None, services.cache if hosted else None,
        )


def test_on_premise_only_the_connection_is_deleted() -> None:
    """No portal, no cache"""
    services = _services()

    assert _follow_ups(services, hosted=False) == []
    services.connections.delete_connection.assert_called_once_with(CONNECTION_ID)
    services.portal.delete_scheduler_id.assert_not_called()
    services.cache.delete_cached_user.assert_not_called()


@pytest.mark.parametrize('answer', [False, requests_errors.ConnectionError('down')], ids=['refused', 'unreachable'])
def test_on_premise_a_connection_left_behind_is_named(answer: Any) -> None:
    """What the route answers 500 with"""
    assert _follow_ups(_services(connection=answer), hosted=False) == [CONNECTION_LEFT]


def test_in_the_cloud_everything_goes_in_order() -> None:
    """schedulerId, connection, connectionId - the cache evicted once"""
    services = _services()
    order: list[str] = []
    services.portal.delete_scheduler_id.side_effect = lambda *_a: order.append('schedulerId') or True
    services.connections.delete_connection.side_effect = lambda *_a: order.append('connection') or True
    services.portal.delete_connection_id.side_effect = lambda *_a: order.append('connectionId') or True

    assert _follow_ups(services, hosted=True) == []
    assert order == ['schedulerId', 'connection', 'connectionId']
    services.portal.delete_scheduler_id.assert_called_once_with(SCHEDULER_ID, USER.email, USER.database)
    services.portal.delete_connection_id.assert_called_once_with(CONNECTION_ID, USER.email, USER.database)
    services.cache.delete_cached_user.assert_called_once_with(USER.email)


@pytest.mark.parametrize('answer', [False, requests_errors.Timeout('slow')], ids=['refused', 'unreachable'])
def test_a_connection_left_behind_keeps_its_portal_id(answer: Any) -> None:
    """Removing the connectionId would orphan a connection no tenant can reach"""
    services = _services(connection=answer)

    assert _follow_ups(services, hosted=True) == [CONNECTION_LEFT]
    services.portal.delete_connection_id.assert_not_called()
    services.cache.delete_cached_user.assert_called_once_with(USER.email)


@pytest.mark.parametrize('answer', [False, AuthError('login')], ids=['refused', 'unreachable'])
def test_a_scheduler_id_left_behind_does_not_stop_the_rest(answer: Any) -> None:
    """The connection and its id are still deleted"""
    services = _services(scheduler_id=answer)

    assert _follow_ups(services, hosted=True) == [SCHEDULER_ID_LEFT]
    services.connections.delete_connection.assert_called_once_with(CONNECTION_ID)
    services.portal.delete_connection_id.assert_called_once()


@pytest.mark.parametrize('answer', [False, requests_errors.ConnectionError('down')], ids=['refused', 'unreachable'])
def test_a_connection_id_left_behind_is_named(answer: Any) -> None:
    """The connection is gone, the portal still lists it"""
    assert _follow_ups(_services(connection_id=answer), hosted=True) == [CONNECTION_ID_LEFT]


def test_everything_left_behind_is_named_in_order() -> None:
    """Every step attempted, every failure named"""
    services = _services(scheduler_id=False, connection=False)

    assert _follow_ups(services, hosted=True) == [SCHEDULER_ID_LEFT, CONNECTION_LEFT]


def test_the_cache_is_evicted_even_when_a_step_raises_a_bug() -> None:
    """The portal may have changed already - stale cached ids must not survive"""
    services = _services(scheduler_id=TypeError('bug'))

    with pytest.raises(TypeError):
        _follow_ups(services, hosted=True)

    services.cache.delete_cached_user.assert_called_once_with(USER.email)

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
Unit tests for cmdb.interface.gunicorn.WebCmdbService._run

The web service forks gunicorn only once it runs a single thread: its database manager starts no keep-alive, the
connection the start-up work opened is closed, and the wait for the other threads comes before the fork - which is
taken from the explicit fork context. In the hosted cloud - and only there - the best-practice repository is synced
first, before the REST API is built and any worker forked. Everything the run builds is stubbed; nothing is forked
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

import cmdb
from cmdb.interface import gunicorn as module
from cmdb.interface.gunicorn import WebCmdbService
from cmdb.process_management.process_constants import EXIT_CODE_FAILED, EXIT_CODE_STOPPED
# -------------------------------------------------------------------------------------------------------------------- #

SECTION: dict[str, Any] = {'host': 'localhost', 'port': 27017, 'database_name': 'cmdb'}


@pytest.fixture(name='steps')
def fixture_steps(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], MagicMock, MagicMock]:
    """Every collaborator stubbed, each recording when it ran; yields the order, the manager class and the context"""
    order: list[str] = []
    reader = MagicMock()
    reader.return_value.get_all_values_from_section.return_value = dict(SECTION)
    manager_class = MagicMock(name='MongoDatabaseManager')
    manager_class.return_value.close.side_effect = lambda: order.append('close')
    context = MagicMock(name='FORK_CONTEXT')
    context.Process.return_value.start.side_effect = lambda: order.append('fork')
    context.Process.return_value.join.side_effect = lambda: order.append('join')

    monkeypatch.setattr(module, 'SystemConfigReader', reader)
    monkeypatch.setattr(module, 'MongoDatabaseManager', manager_class)
    monkeypatch.setattr(module, 'create_app', MagicMock())
    monkeypatch.setattr(module, 'create_rest_api', MagicMock(side_effect=lambda dbm: order.append('rest_api')))
    monkeypatch.setattr(module, 'DispatcherMiddleware', MagicMock())
    monkeypatch.setattr(module, 'HTTPServer', MagicMock())
    monkeypatch.setattr(module, 'wait_until_single_threaded', lambda: order.append('wait') or [])
    monkeypatch.setattr(module, 'FORK_CONTEXT', context)
    monkeypatch.setattr(module, 'sync_best_practice_repository', lambda: order.append('sync'))

    return order, manager_class, context


def test_the_manager_starts_no_keepalive(steps) -> None:
    """A thread must not run across the fork"""
    _order, manager_class, _context = steps

    WebCmdbService()._run()  # pylint: disable=protected-access

    assert manager_class.call_args.kwargs['start_keepalive'] is False


def test_the_connection_is_closed_and_the_threads_awaited_before_the_fork(steps) -> None:
    """Start-up work, close, wait, fork, join - in that order"""
    order, _manager_class, _context = steps

    WebCmdbService()._run()  # pylint: disable=protected-access

    assert order == ['rest_api', 'close', 'wait', 'fork', 'join']


def test_gunicorn_is_forked_from_the_explicit_context(steps) -> None:
    """Its target is the server's run, the handle kept for the shutdown"""
    _order, _manager_class, context = steps
    service = WebCmdbService()

    service._run()  # pylint: disable=protected-access

    assert context.Process.call_args.kwargs['target'] is module.HTTPServer.return_value.run
    assert service._webserver_proc is context.Process.return_value  # pylint: disable=protected-access


@pytest.mark.parametrize('cloud, local, synced', [
    (True, False, True), (True, True, False), (False, False, False),
], ids=['hosted-cloud', 'local-cloud', 'on-premise'])
def test_the_repository_is_synced_first_in_the_hosted_cloud_only(steps, monkeypatch: pytest.MonkeyPatch,
                                                                 cloud: bool, local: bool, synced: bool) -> None:
    """Before the REST API is built and gunicorn forked"""
    order, _manager_class, _context = steps
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', cloud)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', local)

    WebCmdbService()._run()  # pylint: disable=protected-access

    assert order == (['sync'] if synced else []) + ['rest_api', 'close', 'wait', 'fork', 'join']


def test_gunicorn_ending_unasked_is_recorded_as_a_failure(steps, caplog: pytest.LogCaptureFixture) -> None:
    """The join returned without a SIGTERM to this service: exit 1, gunicorn's own code logged"""
    _order, _manager_class, context = steps
    context.Process.return_value.exitcode = 0
    service = WebCmdbService()

    service._run()  # pylint: disable=protected-access

    assert service._exit_code == EXIT_CODE_FAILED  # pylint: disable=protected-access
    assert 'The web server exited unexpectedly with code 0' in caplog.text


def test_a_new_web_service_would_stop_with_0() -> None:
    """Nothing failed yet - a SIGTERM stops it cleanly"""
    assert WebCmdbService()._exit_code == EXIT_CODE_STOPPED  # pylint: disable=protected-access


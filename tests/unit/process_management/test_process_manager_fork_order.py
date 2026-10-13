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
Unit tests for how ProcessManager.start_app forks the services

Every service is forked from the explicit fork context, and every fork happens before the first controller thread
starts - so the main process never forks while another of its threads runs. A service that fails to start still
leaves the ones started before it supervised. Nothing is forked: the context and the controller are stubbed
"""
from unittest.mock import MagicMock

import pytest

from cmdb.process_management import process_manager as module
from cmdb.process_management.cmdb_process import CmdbProcess
from cmdb.process_management.process_manager import ProcessManager
# -------------------------------------------------------------------------------------------------------------------- #

SERVICES: list[CmdbProcess] = [
    CmdbProcess('first', 'tests.first.Service'),
    CmdbProcess('second', 'tests.second.Service'),
]


@pytest.fixture(name='recorded')
def fixture_recorded(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], MagicMock]:
    """Two services, a stubbed fork context and controller recording the order; yields it and the context"""
    order: list[str] = []
    context = MagicMock(name='FORK_CONTEXT')

    def _process(target, name):  # pylint: disable=unused-argument
        process = MagicMock(name=name)
        process.start.side_effect = lambda: order.append(f'fork {name}')
        return process

    context.Process.side_effect = _process
    controller = MagicMock(side_effect=lambda process, *_args: MagicMock(
        start=MagicMock(side_effect=lambda: order.append(f'controller {process._mock_name}'))))

    monkeypatch.setattr(ProcessManager, '_initialize_service_definitions', lambda self: list(SERVICES))
    monkeypatch.setattr(module, 'FORK_CONTEXT', context)
    monkeypatch.setattr(module, 'ProcessController', controller)
    monkeypatch.setattr(module, 'load_class', lambda path: MagicMock())

    return order, context


def test_every_fork_comes_before_the_first_controller(recorded) -> None:
    """The main process forks while it runs a single thread"""
    order, _context = recorded

    assert ProcessManager().start_app() is True
    assert order == ['fork first', 'fork second', 'controller first', 'controller second']


def test_the_services_are_forked_from_the_explicit_context(recorded) -> None:
    """One process per service, named after it"""
    _order, context = recorded

    ProcessManager().start_app()

    assert [call.kwargs['name'] for call in context.Process.call_args_list] == ['first', 'second']


def test_a_failed_start_still_supervises_the_ones_started(recorded, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first runs, the second fails to load - the first gets its controller"""
    order, _context = recorded
    classes = iter([MagicMock(), RuntimeError('no such service')])

    def _load(_path):
        value = next(classes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(module, 'load_class', _load)

    assert ProcessManager().start_app() is False
    assert order == ['fork first', 'controller first']

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
Unit tests: the exit code DataGerry ends with - ProcessManager.stop_app / wait / exit_code, ProcessController's crash
path and AbstractCmdbService.stop

0 only after a requested stop, 1 after a crash or a failed start; the first stop_app call decides the reason, and one
call tears the services down however many arrive (a SIGTERM during a crash, a handler nested in a teardown). Nothing is
forked here; tests/integration/system/test_integration_process_exit_codes.py runs the real thing in subprocesses
"""
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.process_management.process_constants import EXIT_CODE_FAILED, EXIT_CODE_STOPPED, WAIT_POLL_SECONDS
from cmdb.process_management.process_controller import ProcessController
from cmdb.process_management.process_manager import ProcessManager
from cmdb.process_management.service import AbstractCmdbService
# -------------------------------------------------------------------------------------------------------------------- #

CHILD_EXIT_CODE: int = 3


@pytest.fixture(name='manager')
def fixture_manager(monkeypatch: pytest.MonkeyPatch) -> tuple[ProcessManager, list[str]]:
    """A ProcessManager whose teardown only records that it ran"""
    teardowns: list[str] = []
    manager = ProcessManager()
    monkeypatch.setattr(manager, '_ProcessManager__tear_down', lambda: teardowns.append('teardown'))

    return manager, teardowns


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the stop reason                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_nothing_is_decided_while_the_app_runs(manager) -> None:
    """No stop yet, no exit code"""
    assert manager[0].exit_code is None


def test_a_requested_stop_is_0(manager) -> None:
    """stop_app without a reason - the signal handlers' call"""
    process_manager, teardowns = manager

    process_manager.stop_app()

    assert (process_manager.exit_code, teardowns) == (EXIT_CODE_STOPPED, ['teardown'])


def test_a_crash_is_1(manager) -> None:
    """The controller's call"""
    process_manager, _teardowns = manager

    process_manager.stop_app(EXIT_CODE_FAILED)

    assert process_manager.exit_code == EXIT_CODE_FAILED


@pytest.mark.parametrize('first, second', [
    (EXIT_CODE_FAILED, EXIT_CODE_STOPPED), (EXIT_CODE_STOPPED, EXIT_CODE_FAILED),
])
def test_the_first_reason_wins_and_one_call_tears_down(manager, first: int, second: int) -> None:
    """A SIGTERM after a crash keeps the crash; a crash after a SIGTERM keeps the stop; one teardown"""
    process_manager, teardowns = manager

    process_manager.stop_app(first)
    process_manager.stop_app(second)

    assert (process_manager.exit_code, teardowns) == (first, ['teardown'])


def test_a_stop_nested_in_the_teardown_returns_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signal handler running on the thread that tears down does not deadlock and does not tear down again"""
    process_manager = ProcessManager()
    teardowns: list[str] = []

    def teardown() -> None:
        teardowns.append('teardown')
        process_manager.stop_app(EXIT_CODE_STOPPED)

    monkeypatch.setattr(process_manager, '_ProcessManager__tear_down', teardown)

    process_manager.stop_app(EXIT_CODE_FAILED)

    assert (process_manager.exit_code, teardowns) == (EXIT_CODE_FAILED, ['teardown'])


def test_concurrent_stops_tear_down_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crash and a SIGTERM at the same moment: the services are torn down once"""
    process_manager = ProcessManager()
    teardowns: list[str] = []
    barrier = threading.Barrier(2)
    monkeypatch.setattr(process_manager, '_ProcessManager__tear_down', lambda: teardowns.append('teardown'))

    def stop(code: int) -> None:
        barrier.wait()
        process_manager.stop_app(code)

    threads = [threading.Thread(target=stop, args=(code,)) for code in (EXIT_CODE_FAILED, EXIT_CODE_STOPPED)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert teardowns == ['teardown']
    assert process_manager.exit_code in (EXIT_CODE_FAILED, EXIT_CODE_STOPPED)


def test_the_real_teardown_signals_and_clears_the_services() -> None:
    """The flag is set, each live service terminated and joined, the registries emptied"""
    process_manager = ProcessManager()
    process = MagicMock()
    process.is_alive.side_effect = [True, False]
    process_manager._ProcessManager__process_list.append(process)  # pylint: disable=protected-access

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr('cmdb.process_management.process_manager.sleep', lambda _seconds: None)
        process_manager.stop_app()

    process.terminate.assert_called_once()
    process.join.assert_called_once()
    assert not process_manager._ProcessManager__process_list  # pylint: disable=protected-access


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       wait                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _controller(alive_rounds: int) -> MagicMock:
    """A controller thread alive for that many checks"""
    controller = MagicMock()
    controller.is_alive.side_effect = [True] * alive_rounds + [False]

    return controller


def test_wait_joins_each_controller_in_short_slices_and_answers_the_code(manager) -> None:
    """Short joins keep the main thread's signal handlers responsive; the answer is the stop reason"""
    process_manager, _teardowns = manager
    controllers = [_controller(2), _controller(0)]
    process_manager._ProcessManager__process_controllers.extend(controllers)  # pylint: disable=protected-access
    process_manager.stop_app(EXIT_CODE_FAILED)

    assert process_manager.wait() == EXIT_CODE_FAILED
    assert [call.args for call in controllers[0].join.call_args_list] == [(WAIT_POLL_SECONDS,)] * 2
    controllers[1].join.assert_not_called()


def test_wait_answers_0_after_a_requested_stop(manager) -> None:
    """The SIGTERM path"""
    process_manager, _teardowns = manager
    process_manager.stop_app()

    assert process_manager.wait() == EXIT_CODE_STOPPED


def test_a_stop_nobody_gave_a_reason_for_counts_as_a_failure() -> None:
    """Services gone without any stop_app call: a supervisor should restart"""
    assert ProcessManager().wait() == EXIT_CODE_FAILED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ProcessController                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _process(exitcode: int) -> MagicMock:
    """A finished child process"""
    process = MagicMock()
    process.name = 'webapp'
    process.exitcode = exitcode

    return process


def test_a_child_that_exits_unasked_stops_the_app_as_a_crash(caplog: pytest.LogCaptureFixture) -> None:
    """The callback gets EXIT_CODE_FAILED; the child's own code is logged"""
    callback = MagicMock()

    ProcessController(_process(CHILD_EXIT_CODE), threading.Event(), callback).run()

    callback.assert_called_once_with(EXIT_CODE_FAILED)
    assert f"Service 'webapp' exited unexpectedly with code {CHILD_EXIT_CODE}" in caplog.text


def test_a_child_that_exits_after_a_requested_stop_calls_nothing() -> None:
    """The shutdown flag was set: no crash"""
    callback = MagicMock()
    flag = threading.Event()
    flag.set()

    ProcessController(_process(0), flag, callback).run()

    callback.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               AbstractCmdbService.stop                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_service_stops_with_0_by_default() -> None:
    """The SIGTERM path"""
    with pytest.raises(SystemExit) as stopped:
        AbstractCmdbService().stop()

    assert stopped.value.code == EXIT_CODE_STOPPED


def test_a_service_whose_work_ended_unasked_stops_with_1() -> None:
    """_run recorded the failure"""
    service: Any = AbstractCmdbService()
    service._exit_code = EXIT_CODE_FAILED  # pylint: disable=protected-access

    with pytest.raises(SystemExit) as stopped:
        service.stop()

    assert stopped.value.code == EXIT_CODE_FAILED

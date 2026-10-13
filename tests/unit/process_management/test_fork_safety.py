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
Unit tests for cmdb.process_management.fork_safety

Every service process is forked from the explicit fork context, whatever the platform default; the thread census
leaves the caller out; the wait returns once the other threads end, and names - and warns about - one that outlives
the timeout instead of blocking the start
"""
import threading
from collections.abc import Iterator

import pytest

from cmdb.process_management import fork_safety
from cmdb.process_management.fork_safety import (
    FORK_CONTEXT,
    FORK_START_METHOD,
    other_live_threads,
    wait_until_single_threaded,
)
# -------------------------------------------------------------------------------------------------------------------- #

SHORT_WAIT: float = 0.05
THREAD_NAME: str = 'fork-safety-test-thread'


@pytest.fixture(name='held_thread')
def fixture_held_thread() -> Iterator[threading.Thread]:
    """A thread that runs until the test lets it go"""
    release = threading.Event()
    thread = threading.Thread(target=release.wait, name=THREAD_NAME, daemon=True)
    thread.start()

    yield thread

    release.set()
    thread.join()


def test_service_processes_are_forked() -> None:
    """Never the platform default - spawn on macOS, forkserver on Linux from Python 3.14"""
    assert FORK_START_METHOD == 'fork'
    assert FORK_CONTEXT.get_start_method() == FORK_START_METHOD


def test_the_caller_is_not_counted(held_thread: threading.Thread) -> None:
    """Only the others"""
    others = other_live_threads()

    assert held_thread in others
    assert threading.current_thread() not in others


def test_the_wait_returns_once_the_others_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A thread that ends in time is waited for, nothing remains"""
    done = threading.Thread(target=lambda: None, name=THREAD_NAME)
    monkeypatch.setattr(fork_safety, 'other_live_threads', iter([[done], []]).__next__)
    done.start()

    assert not wait_until_single_threaded(SHORT_WAIT)
    assert not done.is_alive()


def test_a_thread_outliving_the_wait_is_named_and_warned_about(held_thread: threading.Thread,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    """The fork goes ahead - the warning says what may break"""
    with caplog.at_level('WARNING'):
        remaining = wait_until_single_threaded(SHORT_WAIT)

    assert held_thread.name in remaining
    assert THREAD_NAME in caplog.text

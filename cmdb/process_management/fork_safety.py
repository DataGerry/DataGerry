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
Forking the service processes safely

DataGerry runs as a tree of forked processes: the main process forks the web service, the web service forks the
gunicorn arbiter, gunicorn forks its workers. Two rules keep that tree sound on every platform:

**Every process is forked explicitly** (`FORK_CONTEXT`), never by the platform's default start method. The default is
``spawn`` on macOS and Windows and becomes ``forkserver`` on Linux with Python 3.14; both start a fresh interpreter
and pickle the process target, and the web server's target carries the application and its database manager, which
cannot be pickled.

**A process forks only while it runs a single thread** (`wait_until_single_threaded`). A thread running in the
parent is gone in the child, together with whatever lock it held: on Linux that can deadlock the child, and on macOS
the Objective-C runtime crashes a child forked from a multithreaded parent the first time it initialises a class - a
DNS lookup is enough (`+[NSMutableString initialize] may have been in progress in another thread when fork() was
called`). So the web service closes its database connection, whose driver runs monitor threads, before it forks
gunicorn, and every worker connects again after its own fork
"""
import multiprocessing
import threading
import time
from logging import Logger, getLogger
from multiprocessing.context import BaseContext
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: The start method of every DataGerry service process
FORK_START_METHOD: str = 'fork'

#: The context every service process is started from - see the module docstring
FORK_CONTEXT: BaseContext = multiprocessing.get_context(FORK_START_METHOD)

#: How long a process waits for its other threads to end before it forks anyway, in seconds
FORK_THREAD_WAIT_SECONDS: float = 5.0


def other_live_threads() -> list[threading.Thread]:
    """
    The threads of this process still running, other than the calling one

    Returns:
        list[threading.Thread]: The running threads, the caller excluded
    """
    current: threading.Thread = threading.current_thread()

    return [thread for thread in threading.enumerate() if thread is not current and thread.is_alive()]


def wait_until_single_threaded(timeout: float = FORK_THREAD_WAIT_SECONDS) -> list[str]:
    """
    Waits until the calling thread is the only one running, for at most `timeout` seconds

    Called right before a fork, after whatever started the threads was told to stop (a database client closed). A
    thread still running after the timeout is named in a warning and the fork goes ahead: refusing to start the web
    server would be worse than the risk the warning describes

    Args:
        timeout (float): Seconds to wait in all. Defaults to `FORK_THREAD_WAIT_SECONDS`

    Returns:
        list[str]: The names of the threads still running when the wait ended; empty when the process is
            single-threaded
    """
    deadline: float = time.monotonic() + timeout

    for thread in other_live_threads():
        thread.join(max(0.0, deadline - time.monotonic()))

    remaining: list[str] = [thread.name for thread in other_live_threads()]

    if remaining:
        LOGGER.warning("[fork_safety] Forking while %d other thread(s) still run: %s - the child may crash on macOS "
                       "or deadlock", len(remaining), ', '.join(remaining))

    return remaining

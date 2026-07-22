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
Supervises a single multiprocessing child process on behalf of ProcessManager

A ProcessController is a Thread that blocks on its child's join() and, when the
child exits, decides whether the exit was graceful (the shared shutdown flag is
set) or a crash (the flag is unset). On crash it invokes the provided callback,
which is wired by ProcessManager to its own stop_app so the whole application
tears down when any registered service dies unexpectedly
"""
from logging import Logger, getLogger
<<<<<<< HEAD
=======
from multiprocessing import Process
>>>>>>> origin/version-3.2
from threading import Thread, Event
from typing import Callable
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ProcessController - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ProcessController(Thread):
    """
    Watches a single child process and triggers application shutdown on a crash

    One ProcessController is attached per service spawned by ProcessManager. The
    controller runs in its own daemon-style thread, blocks on the child's join,
    and uses the shared shutdown flag to distinguish a requested stop from an
    unexpected exit
    """

    def __init__(self, process: Process, flag_shutdown: Event, cb_shutdown: Callable[[], None]) -> None:
        """
        Initializes a ProcessController bound to a single child process

        Stores references to the supervised process, the shared shutdown flag,
        and the crash callback. No work happens here; the actual supervision
        starts when start() is called by ProcessManager

        Args:
            process (Process): The multiprocessing.Process to supervise; the
                controller will block on its join() in run()
            flag_shutdown (Event): Shared Event set by ProcessManager.stop_app;
                when set at the time the child exits, the exit is treated as
                graceful and cb_shutdown is NOT invoked
            cb_shutdown (Callable[[], None]): Invoked from this controller's
                thread when the child exits while flag_shutdown is unset.
                Typically ProcessManager.stop_app
        """
        super().__init__()
        self.__process: Process = process
        self.__flag_shutdown: Event = flag_shutdown
        self.__cb_shutdown: Callable[[], None] = cb_shutdown


    def run(self) -> None:
        """
        Blocks on the supervised process and invokes the crash callback on unexpected exit

        Waits for the child's join() to return, then checks the shared shutdown
        flag: if the flag is set the exit was requested by ProcessManager and
        nothing further is done; if it is unset the exit is treated as a crash
        and cb_shutdown is invoked to tear the rest of the application down

        Note: there is a small TOCTOU window between join() returning and the
        flag check; if another path sets the flag inside that window the
        callback will still fire. cb_shutdown (ProcessManager.stop_app) is not
        synchronized, so concurrent invocations from sibling controllers or the
        SIGTERM handler can race on the manager's registries
        """
        self.__process.join()

        if not self.__flag_shutdown.is_set():
            self.__cb_shutdown()

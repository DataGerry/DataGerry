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
Stub services for the exit-code tests - what ProcessManager forks in place of the web service

``CrashingService`` ends at once with a non-zero code, the way the web service ends when its boot routine fails;
``WaitingService`` reports that it runs and then waits until it is terminated, the way the web service serves. They are
loaded by class path (``load_class``), so they live in an importable module
"""
import signal
import sys
import time
from types import FrameType
# -------------------------------------------------------------------------------------------------------------------- #

#: What the crashing service exits with - anything but 0
CRASH_EXIT_CODE: int = 3
#: The line the waiting service prints once it runs
READY_LINE: str = 'stub service ready'
#: How long the waiting service sleeps between looks - it is woken by a signal long before
IDLE_SECONDS: float = 3600.0


def _exit_cleanly(_signum: int, _frame: FrameType | None) -> None:
    """A SIGTERM ends the waiting service with 0, as the web service's own handler does"""
    sys.exit(0)


class CrashingService:
    """Ends at once with CRASH_EXIT_CODE"""

    def start(self) -> None:
        """The service body"""
        sys.exit(CRASH_EXIT_CODE)


class WaitingService:
    """Runs until it is terminated"""

    def start(self) -> None:
        """The service body: says it runs, then sleeps until a SIGTERM ends it with 0"""
        signal.signal(signal.SIGTERM, _exit_cleanly)
        print(READY_LINE, flush=True)

        while True:
            time.sleep(IDLE_SECONDS)

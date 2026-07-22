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
Lifecycle base class for every long-running DataGerry service

`AbstractCmdbService` is the abstract template `ProcessManager.start_app` runs inside each
spawned `multiprocessing.Process`. Subclasses (currently only `WebCmdbService`) supply the
actual daemon work in `_run` and, optionally, custom termination logic in `_shutdown`; this
class handles the surrounding machinery — per-process logging setup, the `_event_shutdown`
threading.Event, the SIGTERM handler, the optional `_run`-in-a-thread plumbing, and the
final `sys.exit(0)` in `stop`
"""
<<<<<<< HEAD
from logging import Logger, getLogger, config
=======
from logging import Logger, getLogger
from logging.config import dictConfig
>>>>>>> origin/version-3.2
import signal
import sys
import threading

from cmdb.utils.logger import get_logging_conf
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              AbstractCmdbService - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class AbstractCmdbService:
    """
    Lifecycle template for long-running DataGerry services spawned by `ProcessManager`

    Subclassing contract: assign `_name`, set `_threaded_service` if the daemon body should
    run on its own thread, and implement `_run` (the daemon body). `_run` is invoked through
    `_run_and_signal`, which guarantees `_event_shutdown` is set on return or raise, so
    implementations don't need to signal completion manually — they simply return when their
    work is done. Long-running implementations that need to react to shutdown requests can
    poll or wait on `self._event_shutdown` themselves. Subclasses may also override
    `_shutdown` to add cleanup before the base-class `stop()` runs

    Lifecycle (one `multiprocessing.Process` per service):
      1. `start()` configures process-wide logging from `get_logging_conf()` (selects
         `<_name>.log` as the daemon file) and installs a SIGTERM handler that routes to
         `_shutdown`
      2. `start()` invokes `_run` either in a worker thread (`_threaded_service=True`) or
         inline, then blocks on `_event_shutdown.wait()`
      3. Shutdown trigger is either external (SIGTERM → `_shutdown` → `stop`) or internal
         (some code path sets `_event_shutdown`, releasing `wait()`; `start()` then calls
         `_shutdown(None, None)` itself)
      4. `stop()` joins the worker thread (if any), logs progress, and `sys.exit(0)`s the
         process
    """

    def __init__(self) -> None:
        """
        Seeds the per-instance lifecycle flags and runtime slots with their defaults

        The runtime slots (`_event_shutdown`, `_thread_service`) are filled in by `start()`
        and stay None until then
        """
        self._name = "abstract-service"
        self._threaded_service = True
        self._multiprocessing = False

        self._event_shutdown = None
        self._thread_service = None


    def start(self):
        """
        Entry point invoked inside the spawned `multiprocessing.Process`

        Runs once per service lifetime and blocks until shutdown. Performs, in order:
        per-process logging setup via `get_logging_conf()` (the `_name` value selects the
        daemon log file), creation of the `_event_shutdown` threading.Event, installation of
        the SIGTERM handler pointing at `_shutdown`, dispatch of `_run_and_signal` (in a
        thread when `_threaded_service` is True, inline otherwise) which guarantees
        `_event_shutdown` is set once `_run` returns or raises, a blocking `wait()` on the
        shutdown event, and finally an explicit `_shutdown(None, None)` so internally-
        triggered shutdowns go through the same path as signal-triggered ones. The signal
        path short-circuits this last call because `stop()` has already `sys.exit(0)`ed
        """
        logging_conf = get_logging_conf()
<<<<<<< HEAD
        config.dictConfig(logging_conf)
=======
        dictConfig(logging_conf)
>>>>>>> origin/version-3.2

        LOGGER.info("Starting %s ...", self._name)

        self._event_shutdown = threading.Event()
        signal.signal(signal.SIGTERM, self._shutdown)

        if self._threaded_service:
            self._thread_service = threading.Thread(target=self._run_and_signal, daemon=False)
            self._thread_service.start()
        else:
            self._run_and_signal()

        self._event_shutdown.wait()

        self._shutdown(None, None)


    def _run_and_signal(self):
        """
        Invokes `_run` and always sets `_event_shutdown` when it returns

        Wrapper around `_run` that closes the door on subclass implementations forgetting to
        signal completion: whether `_run` returns normally, finishes its work and exits, or
        raises, the shutdown event is set in the `finally` block so the blocking `wait()`
        inside `start()` always wakes. Subclasses implement `_run`; they do not override
        this helper
        """
        try:
            self._run()
        finally:
            if self._event_shutdown is not None:
                self._event_shutdown.set()


    def _run(self):
        """
        Daemon body to be implemented by subclasses

        Implementations should return when their work is done — the surrounding
        `_run_and_signal` wrapper guarantees `_event_shutdown` is set on return, so a
        subclass does not need to set it manually. Long-running implementations that need to
        react to shutdown requests can poll or wait on `self._event_shutdown` themselves.
        The default implementation is a no-op
        """


    #pylint: disable=unused-argument
    def _shutdown(self, signum, frame):
        """
        SIGTERM handler / internal shutdown bridge that defers to `stop`

        Bound to `signal.SIGTERM` in `start()`, and also called explicitly by `start()` after
        `_event_shutdown` is set, so the same teardown path is used for both signal-driven
        and internally-driven shutdowns. Subclasses override this to insert pre-stop cleanup
        (e.g. terminating nested child processes) before calling `stop()` themselves or via
        `super()._shutdown(...)`

        Args:
            signum: Signal number passed by `signal.signal`; unused (kept for the callback
                signature)
            frame: Current stack frame passed by `signal.signal`; unused
        """
        self.stop()


    def stop(self):
        """
        Sets the shutdown event, joins the worker thread (if any) and exits the process

        Called by `_shutdown` and by subclass overrides. Tolerates being invoked before
        `start()` has initialised `_event_shutdown` (defensive — currently no caller hits
        this path). Calls `sys.exit(0)`, which raises `SystemExit` — when invoked from the
        SIGTERM handler this unwinds out of the signal callback and terminates the process
        while `start()` is still in `_event_shutdown.wait()`
        """
        LOGGER.info("shutdown %s ...", self._name)
        if self._event_shutdown is not None:
            self._event_shutdown.set()
        if self._threaded_service and self._thread_service:
            LOGGER.debug("wait for termination of service thread")
            self._thread_service.join(5)
            LOGGER.debug("service thread terminated")
        LOGGER.info("shutdown %s completed", self._name)
        sys.exit(0)

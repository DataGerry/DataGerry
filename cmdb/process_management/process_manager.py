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
Process supervisor for the long-running services that make up DataGerry

This module is the second stage of process startup: cmdb/__main__.py parses the
CLI flags, applies the mode globals (__MODE__, __CLOUD_MODE__, __LOCAL_MODE__),
instantiates the SystemConfigReader singleton, and then hands off to the
module-level 'app_manager' (a ProcessManager). The manager spawns each
registered service as its own multiprocessing.Process, attaches a
ProcessController thread per child for crash detection, and tears everything
down on SIGTERM / SIGINT or on the first unexpected child exit. The main thread
then waits in ``wait`` and the process exits with the code it answers: 0 after a
requested stop, 1 after a crash (``process_constants``) - which is what lets a
supervisor such as systemd's ``Restart=on-failure`` restart a crashed DataGerry

Today only one service is registered (WebCmdbService, which serves the Flask
REST API and the bundled Angular SPA under gunicorn). Adding a new service is
a matter of appending a CmdbProcess entry to _initialize_service_definitions;
the spawn / supervision / teardown machinery is service-agnostic

Related modules:
- cmdb.process_management.cmdb_process — value object holding (name, fqcn) for
  one registered service
- cmdb.process_management.process_controller — Thread that supervises a single
  child process and calls back into ProcessManager.stop_app on crash
"""
from logging import Logger, getLogger
import threading
from multiprocessing.process import BaseProcess
from time import sleep

from cmdb.utils import load_class
from cmdb.process_management.fork_safety import FORK_CONTEXT
from cmdb.process_management.cmdb_process import CmdbProcess
from cmdb.process_management.process_controller import ProcessController
from cmdb.process_management.process_constants import EXIT_CODE_FAILED, EXIT_CODE_STOPPED, WAIT_POLL_SECONDS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ProcessManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ProcessManager:
    """
    Lifecycle owner for every long-running DataGerry service process

    Reads the registered service definitions on construction (one CmdbProcess
    per service to spawn) and exposes start_app / stop_app as the only public
    entry points. start_app spawns each service in registration order and
    attaches a ProcessController thread for crash detection; stop_app sets the
    shared shutdown flag and tears down every registered service in reverse
    spawn order

    Single-instance per process: cmdb/__main__.py creates the module-level
    'app_manager' and binds stop_app as the SIGTERM handler. After a graceful
    or crash-induced shutdown the instance is consumed (the shutdown flag is
    set and never cleared) — a retry would require constructing a new
    ProcessManager
    """

    def __init__(self) -> None:
        """
        Initializes a fresh ProcessManager with an empty process registry

        Loads the ordered service definitions from _initialize_service_definitions
        and sets up the empty process / controller lists plus a threading.Event
        shared with every ProcessController. The Event lets controllers distinguish
        a graceful shutdown (flag set) from a child-crash exit (flag unset)
        """
        self.__service_defs: list[CmdbProcess] = self._initialize_service_definitions()
        self.__process_list: list[BaseProcess] = []
        self.__process_controllers: list[ProcessController] = []
        self.__flag_shutdown: threading.Event = threading.Event()
        # Why the application stops - the first stop_app call decides, a later one cannot overwrite it
        self.__exit_code: int | None = None
        # Guards the reason and the teardown claim. Re-entrant: a signal handler runs on the main thread, which may
        # hold it at that moment
        self.__stop_lock: threading.RLock = threading.RLock()
        # Set by the one stop_app call that tears the services down; a later or concurrent call leaves it to that one
        self.__tearing_down: bool = False


    def _initialize_service_definitions(self) -> list[CmdbProcess]:
        """
        Returns the ordered list of services this manager will spawn on start_app

        This is the registration point for managed services: append a CmdbProcess
        (display name, fully-qualified class path) here to have it started by
        start_app. Order matters because services are spawned sequentially and
        torn down in reverse, so any dependencies should be listed before dependants

        Returns:
            list[CmdbProcess]: One entry per service, in spawn order
        """
        return [
            CmdbProcess("webapp", "cmdb.interface.gunicorn.WebCmdbService"),
        ]


    def start_app(self) -> bool:
        """
        Forks one process per registered service definition (`fork_safety.FORK_CONTEXT`)

        For each CmdbProcess entry, dynamically loads the configured class via
        load_class, instantiates it with no arguments, starts a Process whose
        target is the instance's 'start' method, and attaches a ProcessController
        thread that watches the child and triggers stop_app if the child exits
        while the shutdown flag is unset (treated as a crash)

        Returns False on the first failure. Any services that were already
        started in this call are NOT torn down automatically — the caller is
        expected to invoke stop_app to clean up partial state

        Returns:
            bool: True if every service started; False on the first failure
        """
        if not self.__service_defs:
            LOGGER.error("No service definitions found. Nothing to start.")
            return False

        started: list[BaseProcess] = []

        # Every service is forked first, the controller threads started after: a fork must not run while another
        # thread of this process does (cmdb.process_management.fork_safety)
        for service_def in self.__service_defs:
            service_name: str = service_def.name

            try:
                service_class = load_class(service_def.class_path)
                service_instance = service_class()

                process = FORK_CONTEXT.Process(target=service_instance.start, name=service_name)
                process.start()
                self.__process_list.append(process)
                started.append(process)
            except Exception as err:
                LOGGER.error("Failed to start service '%s': %s", service_name, err)
                self.__start_controllers(started)
                return False

        self.__start_controllers(started)

        return True


    def __start_controllers(self, processes: list[BaseProcess]) -> None:
        """
        Attaches one ProcessController thread to each started service process

        Args:
            processes (list[BaseProcess]): The processes started, in start order
        """
        for process in processes:
            proc_controller: ProcessController = ProcessController(process, self.__flag_shutdown, self.stop_app)
            proc_controller.start()
            self.__process_controllers.append(proc_controller)


    @property
    def exit_code(self) -> int | None:
        """
        The exit code the application stops with, decided by the first ``stop_app`` call; None while it runs

        Returns:
            int | None: ``EXIT_CODE_STOPPED`` after a requested stop, ``EXIT_CODE_FAILED`` after a crash
        """
        return self.__exit_code


    def wait(self) -> int:
        """
        Blocks the calling (main) thread until every supervised service has ended, then answers the exit code

        Each controller is joined in short slices (``WAIT_POLL_SECONDS``), so a SIGTERM or SIGINT handler - which
        always runs on the main thread - is not held up by the wait. A controller ends after its child exited:
        either the stop was requested (the shutdown flag was set by ``stop_app``) or the child crashed and the
        controller called ``stop_app`` with ``EXIT_CODE_FAILED``

        Returns:
            int: The code the process exits with - ``EXIT_CODE_STOPPED`` after a requested stop, ``EXIT_CODE_FAILED``
                after a crash; a stop nobody gave a reason for counts as a failure
        """
        for controller in list(self.__process_controllers):
            while controller.is_alive():
                controller.join(WAIT_POLL_SECONDS)

        return self.__exit_code if self.__exit_code is not None else EXIT_CODE_FAILED


    def stop_app(self, exit_code: int = EXIT_CODE_STOPPED) -> None:
        """
        Tears down every running service in reverse spawn order

        Sets the shared shutdown flag (so each ProcessController distinguishes
        this graceful stop from a child crash and skips its crash callback),
        SIGTERMs each process in reverse spawn order, sleeps 1 s to give them a
        chance to exit cleanly, then joins each with a 5 s timeout and SIGKILLs
        any that still did not exit. Both the process and controller registries
        are cleared before returning

        Safe to call concurrently - a SIGTERM arriving while a crash is handled, say. The first call decides the
        exit code (``exit_code``: a crash stays a crash), and only one call tears the services down; a concurrent or a
        later one returns at once and leaves it to the first

        Args:
            exit_code (int): Why the application stops - ``EXIT_CODE_STOPPED`` for a requested stop (the default),
                ``EXIT_CODE_FAILED`` for a crash or a failed start
        """
        with self.__stop_lock:
            if self.__exit_code is None:
                self.__exit_code = exit_code

            if self.__tearing_down:
                return

            self.__tearing_down = True

        self.__tear_down()


    def __tear_down(self) -> None:
        """Sets the shutdown flag, SIGTERMs every service in reverse spawn order, then joins or SIGKILLs it"""
        self.__flag_shutdown.set()
        # go through processes in different order
        for process in reversed(self.__process_list):
            if process.is_alive():
                LOGGER.info("Terminating service: %s (PID: %s)", process.name, process.pid)
                process.terminate()

        # Ensure processes have time to shut down cleanly
        sleep(1)

        # Confirm processes are stopped
        for process in reversed(self.__process_list):
            process.join(timeout=5)  # Give it some time to exit
            if process.is_alive():
                LOGGER.warning("Force killing unresponsive service: %s (PID: %s)", process.name, process.pid)
                process.kill()  # Force kill if terminate() didn't work

        # Clear process lists
        self.__process_list.clear()
        self.__process_controllers.clear()

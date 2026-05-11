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
down on SIGTERM or on the first unexpected child exit

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
import multiprocessing
import threading
from time import sleep

from cmdb.utils.helpers import load_class
from cmdb.process_management.cmdb_process import CmdbProcess
from cmdb.process_management.process_controller import ProcessController
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
        self.__process_list: list[multiprocessing.Process] = []
        self.__process_controllers: list[ProcessController] = []
        self.__flag_shutdown: threading.Event = threading.Event()


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
        Spawns one multiprocessing.Process per registered service definition

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

        for service_def in self.__service_defs:
            service_name: str = service_def.get_name()

            try:
                service_class = load_class(service_def.get_class())
                service_instance = service_class()

                process: multiprocessing.Process = multiprocessing.Process(
                    target=service_instance.start, name=service_name,
                )
                process.start()
                self.__process_list.append(process)
                # start process controller
                proc_controller: ProcessController = ProcessController(
                    process, self.__flag_shutdown, self.stop_app,
                )
                proc_controller.start()
                self.__process_controllers.append(proc_controller)
            except Exception as err:
                LOGGER.error("Failed to start service '%s': %s", service_name, err)
                return False

        return True


    def stop_app(self) -> None:
        """
        Tears down every running service in reverse spawn order

        Sets the shared shutdown flag (so each ProcessController distinguishes
        this graceful stop from a child crash and skips its crash callback),
        SIGTERMs each process in reverse spawn order, sleeps 1 s to give them a
        chance to exit cleanly, then joins each with a 5 s timeout and SIGKILLs
        any that still did not exit. Both the process and controller registries
        are cleared before returning

        Not safe to call concurrently: callers from the SIGTERM handler and a
        crashed-child ProcessController can race on the process and controller
        registries. With one service registered today the window is small in
        practice
        """
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

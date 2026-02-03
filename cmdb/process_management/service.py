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
CmdbService definition
"""
import logging
import signal
import sys
import threading

from cmdb.utils.logger import get_logging_conf
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              AbstractCmdbService - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class AbstractCmdbService:
    """Abstract definition of a CMDB service

    This abstract CmdbService must be implemented to start a process
    in a CMDB context.
    """

    def __init__(self):
        """Create a new instance"""
        # service name
        self._name = "abstract-service"
        # boolean: execute _run() method as own thread
        self._threaded_service = True
        # boolean: multiprocessing service
        self._multiprocessing = False

        # init variables
        self._event_shutdown = None
        self._event_manager = None
        self._thread_service = None


    def start(self):
        """service start"""
        # setup service logging
        logging_conf = get_logging_conf()
        logging.config.dictConfig(logging_conf)

        LOGGER.info("Starting %s ...", self._name)

        # init shutdown handling
        self._event_shutdown = threading.Event()
        signal.signal(signal.SIGTERM, self._shutdown)

        if self._threaded_service:
            # start daemon logic in own thread
            self._thread_service = threading.Thread(target=self._run, daemon=False)
            self._thread_service.start()
        else:
            self._run()

        # wait for shutdown, if daemon logic was terminated
        self._event_shutdown.wait()

        # shutdown daemon explicitly, if shutdown event was set
        self._shutdown(None, None)


    def _run(self):
        """daemon action - to be implemented
        implemented action must check the self._even_shutdown flag for termination
        """


    #pylint: disable=unused-argument
    def _shutdown(self, signam, frame):
        """shutdown handler"""
        self.stop()


    def stop(self):
        """stop the service"""
        LOGGER.info("shutdown %s ...", self._name)
        # set shutdown event
        self._event_shutdown.set()
        # wait for termination of service thread (max 5sec)
        if self._threaded_service and self._thread_service:
            LOGGER.debug("wait for termination of service thread")
            self._thread_service.join(5)
            LOGGER.debug("service thread terminated")
        # exit process
        LOGGER.info("shutdown %s completed", self._name)
        sys.exit(0)


    def _handle_event(self, event):
        """action for handling events

        this should only be a short running function
        long running jobs should be started and handled by the _run() function
        """

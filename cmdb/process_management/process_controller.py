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
Implementation of ProcessController
"""
from logging import Logger, getLogger
from threading import Thread, Event
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ProcessController - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ProcessController(Thread):
    """
    Controlls the state of a process
    """

    def __init__(self, process, flag_shutdown: Event, cb_shutdown):
        """
        Creates a new instance
        
        Args:
            process(multiprocessingProcess): process to control
            flag_shutdown(threading.Event): shutdown flag
            cb_shutdown(func): callback function if a process crashed
        """
        super().__init__()
        self.__process = process
        self.__flag_shutdown = flag_shutdown
        self.__cb_shutdown = cb_shutdown


    def run(self):
        self.__process.join()
        # terminate app, if process crashed
        if not self.__flag_shutdown.is_set():
            self.__cb_shutdown()

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
Server module for web-based services
"""
import logging
import multiprocessing

import cmdb

from cmdb.database import MongoDatabaseManager

from cmdb.process_management.service import AbstractCmdbService
from cmdb.interface.net_app import create_app
from cmdb.interface.docs import create_docs_server
from cmdb.interface.dispatcher_middleware import DispatcherMiddleware
from cmdb.interface.http_server import HTTPServer
from cmdb.interface.rest_api.init_rest_api import create_rest_api
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                WebCmdbService - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class WebCmdbService(AbstractCmdbService):
    """
    Implementation of WebCmdbService
    """

    def __init__(self) -> None:
        super().__init__()
        self._name = "webapp"
        self._threaded_service = False
        self._multiprocessing = True
        self.__webserver_proc = None


    def _run(self):
        mode = 'cloud' if cmdb.__CLOUD_MODE__ and not cmdb.__LOCAL_MODE__ else 'local'
        dbm = MongoDatabaseManager(
            **SystemConfigReader().get_all_values_from_section('Database'),
            mode=mode
        )

        # get WSGI app
        app = DispatcherMiddleware(
                app=create_app(),
                dbm=dbm,
                mounts={
                    '/docs': create_docs_server(),
                    '/rest': create_rest_api(dbm)
                }
        )

        # get gunicorn options
        options = SystemConfigReader().get_all_values_from_section('WebServer')

        # start gunicorn as own process
        webserver = HTTPServer(app, options)
        self.__webserver_proc = multiprocessing.Process(target=webserver.run)
        self.__webserver_proc.start()
        self.__webserver_proc.join()


    def _shutdown(self, signam, frame):
        self.__webserver_proc.terminate()
        self.stop()


    def _handle_event(self, event) -> None:
        """
        Ignore incomming events
        """

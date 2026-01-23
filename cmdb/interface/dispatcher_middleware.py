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

from cmdb.database.mongo_database_manager import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             DispatcherMiddleware - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DispatcherMiddleware:
    """
    A class that represents an application with mountable sub-applications

    This class allows the mounting of sub-applications at specific paths and
    delegates requests to the appropriate sub-application based on the URL path
    """

    def __init__(self, app, dbm: MongoDatabaseManager, mounts=None):
        """
        Initializes the MountableApp instance

        This method stores the main application (`app`) and the optional sub-applications (`mounts`)

        Args:
            app: The main application instance that will handle requests if no sub-application is matched
            mounts (dict, optional): A dictionary mapping URL paths to sub-applications. Defaults to an empty
                                     dictionary if not provided
        """
        self.app = app
        self.mounts = mounts or {}
        self.database_manager = dbm


    def __call__(self, environ, start_response):
        """
        Handles incoming HTTP requests by delegating to the appropriate sub-application
        based on the path in the request, or to the main application if no match is found.

        This method inspects the `PATH_INFO` of the request to identify if the request corresponds 
        to any mounted sub-application. If a match is found, the request is forwarded to that sub-application.
        If no match is found, the request is forwarded to the main application

        Args:
            environ (dict): The WSGI environment dictionary containing request details
            start_response (callable): The function used to start the HTTP response

        Returns:
            The response from the chosen application (either the main app or a mounted sub-app)
        """
        script = environ.get('PATH_INFO', '')
        path_info = ''

        while '/' in script:
            if script in self.mounts:
                app = self.mounts[script]
                break
            script, last_item = script.rsplit('/', 1)
            path_info = f'/{last_item}{path_info}'
        else:
            app = self.mounts.get(script, self.app)

        original_script_name = environ.get('SCRIPT_NAME', '')
        environ['SCRIPT_NAME'] = original_script_name + script
        environ['PATH_INFO'] = path_info

        return app(environ, start_response)

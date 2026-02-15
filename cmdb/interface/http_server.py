# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import os
import logging
import multiprocessing
from gunicorn.app.base import BaseApplication

from cmdb import __MODE__
from cmdb.utils.logger import get_logging_conf
from cmdb.interface.gunicorn_config import post_fork
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  HTTPServer - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class HTTPServer(BaseApplication):
    """Basic server main_application"""

    def __init__(self, app, options=None) -> None:
        self.options = options or {}

        if 'host' in self.options and 'port' in self.options:
            self.options['bind'] = f"{self.options['host']}:{self.options['port']}"

        if 'workers' not in self.options:
            self.options['workers'] = HTTPServer.number_of_workers()

        # Explicitly disable preload
        self.options['preload_app'] = False  # Disable preload
        self.options['worker_class'] = 'sync'
        self.options['disable_existing_loggers'] = False
        self.options['logconfig_dict'] = get_logging_conf()
        self.options['timeout'] = 120
        self.options['daemon'] = True

        self.options['post_fork'] = post_fork

        if __MODE__ in ('DEBUG','TESTING'):
            self.options['reload'] = True
            self.options['check_config'] = True
            LOGGER.debug("Gunicorn starting with auto reload option")

        # optional SSL Configuration
        ssl_enabled = str(self.options.get('ssl', 'false')).lower() == 'true'

        if ssl_enabled:
            certfile = self.options.get('certfile')
            keyfile = self.options.get('keyfile')

            if not certfile or not keyfile:
                raise RuntimeError("SSL enabled but certfile or keyfile not configured")

            if not os.path.exists(certfile):
                raise RuntimeError(f"SSL certfile not found: {certfile}")

            if not os.path.exists(keyfile):
                raise RuntimeError(f"SSL keyfile not found: {keyfile}")

            self.options['certfile'] = certfile
            self.options['keyfile'] = keyfile
        else:
            self.options.pop('ssl', None)
            self.options.pop('certfile', None)
            self.options.pop('keyfile', None)

        protocol = "https" if ssl_enabled else "http"
        LOGGER.info("Interfaces started @ %s://%s:%s", protocol, self.options['host'], self.options['port'])
        self.application = app
        super().__init__()


    def load_config(self) -> None:
        config = {key: value for key, value in self.options.items() if key in self.cfg.settings and value is not None}

        for key, value in config.items():
            self.cfg.set(key.lower(), value)


    def load(self):
        return self.application


    def init(self, parser, opts, args):
        raise NotImplementedError()


    @staticmethod
    def number_of_workers() -> int:
        """
        Returns the optimal number of worker processes based on the system's CPU count

        This method calculates the number of workers by multiplying the number of CPU cores 
        available on the system by 2 and then adding 1. This formula is often used to optimize 
        parallel processing, taking advantage of the available cores while leaving one core 
        available for other system tasks

        Returns:
            int: The calculated number of worker processes
        """
        return (multiprocessing.cpu_count() * 2) + 1

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
`WebCmdbService` — the only service `ProcessManager` registers today

Composes the DataGerry WSGI app (base net_app + Sphinx docs at `/docs` + REST API at `/rest`)
behind a `DispatcherMiddleware`, then runs it under gunicorn. The class plugs into the
`AbstractCmdbService` lifecycle via two hooks: `_run` (build app + start gunicorn) and
`_shutdown` (terminate the gunicorn process on SIGTERM)

Process layout: `ProcessManager` already spawns this service as its own
`multiprocessing.Process` (named `"webapp"`). Inside that process, `_run` spawns one more
nested `multiprocessing.Process` for gunicorn so the SIGTERM handler can terminate the HTTP
server in isolation without taking the WebCmdbService process down through the same signal
path. The nested process is kept on `self._webserver_proc` for `_shutdown` to reach
"""
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

# -------------------------------------------------------------------------------------------------------------------- #
#                                                WebCmdbService - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class WebCmdbService(AbstractCmdbService):
    """
    `AbstractCmdbService` implementation that runs the DataGerry web stack under gunicorn

    Instantiated by `ProcessManager.start_app` (after `load_class` resolves the
    `cmdb.interface.gunicorn.WebCmdbService` path stored on the `CmdbProcess` entry) and
    invoked as `multiprocessing.Process(target=instance.start, name='webapp')`. Once inside
    its dedicated process, `AbstractCmdbService.start` configures logging from
    `get_logging_conf()` (the `"webapp"` name selects the `webapp.log` daemon file), installs
    a SIGTERM handler, and dispatches to `_run`. With `_threaded_service = False`, `_run`
    executes inline on the main thread of this process and blocks until the nested gunicorn
    process exits
    """

    def __init__(self) -> None:
        """
        Configures the base-class lifecycle flags and seeds the gunicorn process handle

        Sets `_name = "webapp"` so the daemon log file resolves to `webapp.log`, forces
        `_threaded_service = False` so `_run` blocks the service main thread directly
        (avoiding an extra worker thread between SIGTERM and the gunicorn process), and
        leaves `_webserver_proc` as `None` until `_run` actually spawns gunicorn
        """
        super().__init__()
        self._name = "webapp"
        self._threaded_service = False
        self._multiprocessing = True
        self._webserver_proc: multiprocessing.Process | None = None


    def _run(self):
        """
        Builds the composite WSGI app, starts gunicorn in a child process and waits for it

        Picks the database mode from the CLI-set globals on the `cmdb` module
        (`__CLOUD_MODE__` wins only when `__LOCAL_MODE__` is unset), constructs the
        `MongoDatabaseManager` from the `[Database]` section of `cmdb.conf`, and assembles
        the WSGI tree with `DispatcherMiddleware`: `create_app()` at the root, the Sphinx
        docs server at `/docs`, the REST API at `/rest`. Gunicorn options come from the
        `[WebServer]` config section. The HTTP server is then started in a nested
        `multiprocessing.Process` and `join()`-ed so this method blocks for the lifetime of
        the web tier — the nesting exists so `_shutdown` can terminate gunicorn directly
        through `self._webserver_proc.terminate()` without relying on signal propagation.
        When `join()` returns on its own (gunicorn died) `_run` returns and the base-class
        `_run_and_signal` wrapper sets `_event_shutdown`, waking `start()`'s wait loop so
        this process exits instead of hanging
        """
        scr = SystemConfigReader()

        mode = 'cloud' if cmdb.__CLOUD_MODE__ and not cmdb.__LOCAL_MODE__ else 'local'
        dbm = MongoDatabaseManager(
            **scr.get_all_values_from_section('Database'),
            mode=mode
        )

        app = DispatcherMiddleware(
                app=create_app(),
                dbm=dbm,
                mounts={
                    '/docs': create_docs_server(),
                    '/rest': create_rest_api(dbm)
                }
        )

        options = scr.get_all_values_from_section('WebServer')

        webserver = HTTPServer(app, options)
        self._webserver_proc = multiprocessing.Process(target=webserver.run)
        self._webserver_proc.start()
        self._webserver_proc.join()


    def _shutdown(self, signum, frame):
        """
        SIGTERM handler: terminates the nested gunicorn process, then defers to `stop`

        Invoked either by `AbstractCmdbService.start` after `self._event_shutdown` fires, or
        directly by the SIGTERM handler installed by the base class. Calls
        `multiprocessing.Process.terminate()` on the gunicorn child (sends SIGTERM) when
        the child is still tracked and alive, then hands off to `self.stop()` which sets the
        shutdown event and `sys.exit(0)`s the process

        Args:
            signum: Signal number when invoked as a signal handler (unused); kept for the
                `signal.signal` callback signature
            frame: Current stack frame when invoked as a signal handler (unused); kept for
                the `signal.signal` callback signature
        """
        if self._webserver_proc is not None and self._webserver_proc.is_alive():
            self._webserver_proc.terminate()
        self.stop()

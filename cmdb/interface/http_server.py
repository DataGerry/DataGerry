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
Embedded gunicorn application that hosts the composed WSGI tree

`WebCmdbService._run` instantiates `HTTPServer(app, options)` inside its dedicated
`multiprocessing.Process`, then forks one more child whose target is `HTTPServer.run`. The
class derives from `gunicorn.app.base.BaseApplication`, which is gunicorn's hook for running
the server programmatically (no CLI / no `gunicorn` entry point). Configuration values come
from the `[WebServer]` section of `cmdb.conf` merged with safe defaults set in `__init__`
"""
import os
from logging import Logger, getLogger
import multiprocessing
from typing import Any
from gunicorn.app.base import BaseApplication

from cmdb import __MODE__
from cmdb.utils.logger import get_logging_conf
from cmdb.interface.gunicorn_config import post_fork
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  HTTPServer - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class HTTPServer(BaseApplication):
    """
    Gunicorn `BaseApplication` subclass that runs DataGerry's composed WSGI app

    Overrides three gunicorn hooks: `load_config` (push the merged options dict into
    gunicorn's `cfg`), `load` (hand the WSGI application back to gunicorn at worker boot)
    and `init` (gunicorn's CLI entry point — unused here, raises). The constructor seeds
    `self.options` from `[WebServer]` config, layers DataGerry-specific defaults
    (`sync` workers, daemonised, fork-safe `post_fork` hook, `preload_app` off), validates
    optional SSL paths, and stores the WSGI app for `load` to return
    """

    def __init__(self, app, options: dict[str, Any] | None = None) -> None:
        """
        Builds the merged gunicorn options dict and stores the WSGI app

        Mutates the caller-supplied `options` dict in place: synthesises `bind` from
        `host` / `port`, fills in `workers` if absent, and pins the DataGerry-specific
        defaults (`worker_class = 'sync'`, `preload_app = False` so workers each construct
        their own app instance post-fork, `daemon = True`, `timeout = 120`, the
        `logconfig_dict` captured from `get_logging_conf()`, and the `post_fork` hook that
        resets the MongoDB connection in each worker — see `gunicorn_config.post_fork` and
        the audit notes for the fork story). When `cmdb.__MODE__` is `DEBUG` or `TESTING`,
        flips `reload` and `check_config` on. SSL handling is conditional on
        `options['ssl']` (string-typed because it comes from the config file); when enabled,
        `certfile` / `keyfile` are validated to exist and the keys are kept on the options
        dict, otherwise they are popped so gunicorn doesn't try to bind TLS

        Args:
            app: WSGI application gunicorn workers will serve — in production the
                `DispatcherMiddleware` composed in `WebCmdbService._run`
            options (dict[str, Any] | None): Server-side configuration, typically the
                `[WebServer]` section of `cmdb.conf`. Must include `host` and `port`; other
                gunicorn keys are passed through `load_config`

        Raises:
            RuntimeError: When `ssl=true` is set but `certfile`/`keyfile` are missing from
                the options or the files don't exist on disk
        """
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
        LOGGER.info("Interfaces configured @ %s://%s:%s", protocol, self.options['host'], self.options['port'])
        self.application = app
        super().__init__()


    def load_config(self) -> None:
        """
        Gunicorn hook: copies the recognised entries from `self.options` into `self.cfg`

        Called once by `BaseApplication.__init__`. Only keys gunicorn already knows about
        (`self.cfg.settings`) are forwarded — unknown keys are silently dropped so DataGerry
        can stash side-channel values (e.g. `host`, `port` before they were folded into
        `bind`) on the options dict without confusing gunicorn
        """
        config = {key: value for key, value in self.options.items() if key in self.cfg.settings and value is not None}

        for key, value in config.items():
            self.cfg.set(key.lower(), value)


    def load(self):
        """
        Gunicorn hook: returns the WSGI application each worker should serve

        Called once per worker, after fork, when gunicorn needs the WSGI callable. Returning
        the pre-built app here (instead of importing it freshly) means the application
        object is inherited across the fork — `preload_app=False` keeps gunicorn from
        importing it ahead of time, but the instance constructed in the parent is still
        carried into each worker

        Returns:
            The WSGI app passed to `__init__`
        """
        return self.application


    def init(self, parser, opts, args):
        """
        Gunicorn hook: would parse CLI options if `gunicorn` were invoked from the shell

        Unused — DataGerry runs gunicorn programmatically via `BaseApplication.run()`, not
        through the `gunicorn` entry point. The method has to exist because gunicorn's
        `BaseApplication` defines it as abstract; raising makes the misuse loud

        Raises:
            NotImplementedError: Always
        """
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

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
WSGI dispatcher that fronts the Flask apps DataGerry serves under one origin

`WebCmdbService._run` wires this middleware as the outermost WSGI app: requests to
`/rest/...` go to the REST API app and everything else to the SPA host. The class
reimplements the algorithm of
`werkzeug.middleware.dispatcher.DispatcherMiddleware` — longest-prefix match on the full
PATH_INFO segments, with the matched prefix moved from `PATH_INFO` to `SCRIPT_NAME` so the
sub-app sees URLs relative to its own mount point
"""
from typing import Iterable
from wsgiref.types import WSGIApplication, WSGIEnvironment, StartResponse

from cmdb.database.mongo_database_manager import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                             DispatcherMiddleware - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DispatcherMiddleware:
    """
    Mounts multiple WSGI sub-applications under a single fallback app by URL prefix

    Used once at process startup to compose the SPA host and the REST API into one WSGI
    application gunicorn serves. Per request, `__call__` strips path
    segments from the right of `PATH_INFO` until what remains matches a mount key; the
    matched portion is appended to `SCRIPT_NAME` and the trailing portion becomes the new
    `PATH_INFO`, so each mounted Flask app sees a path rooted at its own mount point
    """

    def __init__(
        self,
        app: WSGIApplication,
        dbm: MongoDatabaseManager,
        mounts: dict[str, WSGIApplication] | None = None,
    ) -> None:
        """
        Records the fallback app, the mount map and the database manager handle

        Args:
            app (WSGIApplication): The fallback WSGI application invoked when no mount-key
                prefix matches the request `PATH_INFO`. In production this is the SPA host
                built by `cmdb.interface.net_app.create_app`
            dbm (MongoDatabaseManager): Stored as `self.database_manager`. *Required* by
                `cmdb.interface.gunicorn_config.post_fork`, which reaches
                `worker.app.application.database_manager.reset_connection()` on each forked
                worker to drop the inherited MongoClient and force a fresh per-worker
                connection. The attribute is not read by `__call__`, only by the gunicorn
                post-fork hook — do not remove it without updating that hook
            mounts (dict[str, WSGIApplication] | None): Map of URL prefix → sub-application.
                Keys must include a leading slash and no trailing slash (e.g. `'/rest'`).
                Defaults to an empty mapping
        """
        self.app = app
        self.mounts = mounts or {}
        self.database_manager = dbm


    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        """
        Routes one WSGI call to the matching mounted app, falling back to `self.app`

        Algorithm: take the request's `PATH_INFO` and look up the longest prefix in
        `self.mounts` by progressively rsplit'ing at `/`. Each iteration pops the
        rightmost segment off `script` (the candidate mount key) and prepends it back onto
        `path_info` (the sub-app-relative path); when `script` matches a mount, that
        sub-app handles the rest of the request with `SCRIPT_NAME` extended by the matched
        prefix and `PATH_INFO` rewritten to the leftover portion. The `while/else` falls
        through to a final lookup on the empty / single-segment `script` value so a mount
        registered under `''` would also be reachable, then defaults to `self.app`

        Args:
            environ (dict): WSGI environ; `PATH_INFO` and `SCRIPT_NAME` are read and
                rewritten in place before dispatch
            start_response (callable): WSGI `start_response` forwarded to the chosen app

        Returns:
            Iterable[bytes]: Response body iterable returned by whichever app handled the
                request
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

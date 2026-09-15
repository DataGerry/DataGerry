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
Flask app that serves the bundled Angular SPA at the dispatcher's root mount

`create_app()` produces the WSGI application `WebCmdbService._run` mounts at `/` inside the
`DispatcherMiddleware` (alongside `/rest`). The app's job is narrow: serve the
compiled Angular bundle that `make webapp` copies into `cmdb/interface/net_app/datagerry-app/`,
plus two top-level static files (`favicon.ico`, `browserconfig.xml`) read from the package's
`_static/` directory, and fall back to `index.html` on any 404 so the browser can resolve
client-side routes after a hard reload. CORS is enabled wide-open so the dev workflow
(`npm start` on `:4200`) can hit the REST API on a different origin
"""
from flask_cors import CORS

import cmdb
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.config import app_config, config_name_for_mode

from cmdb.interface.net_app.app_routes import app_pages, serve_spa_fallback
# -------------------------------------------------------------------------------------------------------------------- #


def create_app() -> BaseCmdbApp:
    """
    Builds and wires the Flask app for the Angular SPA mount

    Picks the Flask config object from `app_config` with `config_name_for_mode(cmdb.__MODE__)`,
    the same selector `create_rest_api` uses, so all three variants - development, testing,
    production - are reachable from both factories. Enables `flask_cors.CORS` wide-open on the
    whole app so the Angular dev server can call the backend cross-origin; in a production
    deployment the same WSGI app serves UI and API on one origin and CORS is functionally a
    no-op. Registers the `app_pages` blueprint at `/` — that blueprint owns the SPA bundle
    under `datagerry-app/` and the two top-level static routes (`/favicon.ico`,
    `/browserconfig.xml`) backed by the package's `_static/` directory. Finally wires
    `serve_spa_fallback` (defined in `app_routes`) as the app-level 404 handler.

    That handler catches any URL **this app** fails to match; it is not reached for `/rest/...`,
    which `DispatcherMiddleware` hands to a separate Flask app with its own error handling. An
    unmatched client route returns `index.html` so the Angular router can resolve it after a hard
    reload, while a path naming a file keeps its 404 - see `app_routes.serve_spa_fallback`

    Returns:
        BaseCmdbApp: Fully configured Flask app instance, ready to be mounted under
            `DispatcherMiddleware`
    """
    # static_folder=None: this package has no `static/` directory, and Flask's default would
    # register a /static/<path:filename> rule that only ever 404s into the SPA fallback
    app = BaseCmdbApp(__name__, static_folder=None)
    CORS(app)

    app.config.from_object(app_config[config_name_for_mode(cmdb.__MODE__)])

    app.register_blueprint(app_pages, url_prefix='/')
    app.register_error_handler(404, serve_spa_fallback)

    return app

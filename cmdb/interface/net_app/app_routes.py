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
Flask Blueprint that owns the Angular SPA and the top-level browser-asset routes

Registered by `cmdb.interface.net_app.create_app` at `/` inside the `DispatcherMiddleware`,
so everything that isn't `/rest/...` lands here. The blueprint serves the SPA
bundle (`datagerry-app/` as the blueprint's static folder, surfaced at the root because
`static_url_path=""`) plus two explicit ancillary routes for `/favicon.ico` and
`/browserconfig.xml` pointing at the package's `_static/` directory. The SPA fallback view
`serve_spa_fallback` lives in this module too but is registered by `create_app` as the
*app-level* 404 handler so any unmatched URL — inside or outside this blueprint's URL space
— returns `index.html`, letting the Angular router resolve client-side routes after a hard
reload
"""
from os.path import join
from flask import Blueprint, Response, send_from_directory
from werkzeug.exceptions import HTTPException
# -------------------------------------------------------------------------------------------------------------------- #

#: Module-level blueprint registered by `create_app` at `/`. `static_folder="datagerry-app"`
#: with `static_url_path=""` means files inside the Angular bundle are reachable at `/<file>`
#: relative to the mount; the explicit `@route(...)` decorators below take precedence over
#: this catch-all because static URL rules match before `<path:...>` patterns
app_pages = Blueprint("app_pages", __name__, static_folder="datagerry-app", static_url_path="")

# -------------------------------------------------------------------------------------------------------------------- #
@app_pages.route('/')
def default_page() -> Response:
    """
    Serves the Angular SPA's `index.html` for a bare `/` request

    Anchors the SPA at the root of the dispatcher's web mount. The browser then takes over
    via the Angular router and any subsequent deep-link 404s are caught by `serve_spa_fallback`,
    so a user landing on `/` and a user F5-ing on `/some/deep/route` both end up loading the
    same bundle

    Returns:
        Response: `datagerry-app/index.html`
    """
    return app_pages.send_static_file("index.html")


@app_pages.route('/favicon.ico')
def favicon() -> Response:
    """
    Serves the top-level favicon from the package's `_static/` directory

    Returns:
        Response: The `favicon.ico` file
    """
    return send_from_directory(join(app_pages.root_path, '_static'), 'favicon.ico')


@app_pages.route('/browserconfig.xml')
def browser_config() -> Response:
    """
    Serves the Windows tile / browser configuration XML from the package's `_static/` directory

    Returns:
        Response: The `browserconfig.xml` file
    """
    return send_from_directory(join(app_pages.root_path, '_static'), 'browserconfig.xml')


#pylint: disable=unused-argument
def serve_spa_fallback(error: HTTPException) -> Response:
    """
    SPA fallback: returns `index.html` (HTTP 200) for any 404 the app dispatches here

    Defined here next to the rest of the SPA-serving views but registered by `create_app` as
    the *app-level* 404 handler, so it catches unmatched URLs anywhere in the WSGI tree under
    the dispatcher's root mount. Does not issue an HTTP redirect despite serving as a
    fallback — it returns the SPA bundle directly with HTTP 200, letting the Angular router
    interpret the originally-requested path on the client

    Args:
        error (HTTPException): The 404 exception Flask invoked the handler with; unused

    Returns:
        Response: `datagerry-app/index.html`
    """
    return app_pages.send_static_file("index.html")

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

Registered by `cmdb.interface.net_app.create_app` at `/` inside the `DispatcherMiddleware`. The
blueprint serves the SPA bundle (`datagerry-app/` as its static folder, surfaced at the root because
`static_url_path=""`) plus one explicit route, `/favicon.ico`, which answers the browser's root icon probe with the
bundle's own `assets/img/favicon.ico`. **Everything this module serves comes from the bundle**, the one directory the
binary build ships (`make bin`'s `--add-data`): a file read from anywhere else in the package works in a source
checkout and 404s in the shipped product.

The SPA fallback view `serve_spa_fallback` lives here but is registered by `create_app` as the
*app-level* 404 handler, so it catches any URL this app fails to match. It does NOT see `/rest/...`:
the dispatcher hands those to a different Flask app with its own error handling, and this handler is
never consulted for them.

Two rules the fallback follows, both easy to get wrong:

* **Only client routes fall back.** A request for a path that names a file (anything with an
  extension) gets a real 404 instead of `index.html`. Returning HTML with a 200 for a missing
  `.js` chunk or image is the classic post-deploy failure: a browser holding a stale `index.html`
  asks for a chunk that no longer exists and reports a MIME-type error rather than a 404. No Angular
  route in this application contains a dot, so the extension test does not misfire on a deep link
* **A missing bundle says so.** If `index.html` is absent - `make webapp` never ran, or built
  elsewhere - raising `NotFound` a second time *inside* the error handler leaves Flask nothing, which
  Flask cannot handle, so the whole UI host answered 500 and logged two tracebacks per request. It
  now answers 503 with a message naming the cause
"""
from os.path import splitext
from logging import Logger, getLogger

from flask import Blueprint, Response, make_response, request
from werkzeug.exceptions import HTTPException, NotFound
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


#: The SPA entry document, served for `/` and for every unmatched client route
INDEX_FILE: str = 'index.html'

#: The icon `/favicon.ico` answers with, inside the bundle (copied from `app/src/assets/img/` by the Angular build)
FAVICON_BUNDLE_PATH: str = 'assets/img/favicon.ico'

#: Body and status for a request that arrives before `make webapp` has produced a bundle. 503 rather
#: than 404: the URL is right, the deployment is incomplete
MISSING_BUNDLE_MESSAGE: str = (
    'The DataGerry frontend bundle is not available. '
    'Run `make webapp` to build it into cmdb/interface/net_app/datagerry-app/.'
)
MISSING_BUNDLE_STATUS: int = 503

#: `index.html` must never be cached: it names the content-hashed chunks, so a stale copy asks for
#: files that no longer exist. 0 makes Flask emit `no-cache`
NO_CACHE_MAX_AGE: int = 0

#: Everything else in the bundle may be held briefly. Deliberately an hour rather than a year: the
#: JS/CSS chunks are content-hashed and could be cached indefinitely, but `assets/` also carries
#: images and i18n files that are NOT hashed, and this blueprint cannot tell the two apart
ASSET_MAX_AGE: int = 3600


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SpaBlueprint - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SpaBlueprint(Blueprint):
    """
    Blueprint that gives the SPA entry document and the rest of the bundle different cache lifetimes

    Exists only to override `get_send_file_max_age`. Without it Flask falls back to
    `SEND_FILE_MAX_AGE_DEFAULT`, which is `None`, so every bundle chunk is revalidated against the
    server on every page load

    Extends: Blueprint
    """

    def get_send_file_max_age(self, filename: str | None) -> int:
        """
        Decides how long a file this blueprint serves may be cached

        Args:
            filename (str | None): Name of the file being sent, as Flask resolved it

        Returns:
            int: NO_CACHE_MAX_AGE for the SPA entry document, ASSET_MAX_AGE for everything else
        """
        if filename is None or filename.endswith(INDEX_FILE):
            return NO_CACHE_MAX_AGE

        return ASSET_MAX_AGE


#: Module-level blueprint registered by `create_app` at `/`. `static_folder="datagerry-app"` with
#: `static_url_path=""` means files inside the Angular bundle are reachable at `/<file>` relative to
#: the mount. The explicit `@route(...)` rules below still win over that catch-all: Werkzeug sorts
#: rules by specificity, and a literal rule always outranks one containing a converter
app_pages = SpaBlueprint("app_pages", __name__, static_folder="datagerry-app", static_url_path="")

# -------------------------------------------------------------------------------------------------------------------- #


def _send_index() -> Response:
    """
    Sends the SPA entry document, or an explicit 503 when the bundle was never built

    Shared by the `/` route and the 404 fallback, which serve byte-identical responses. The guard is
    what keeps a missing bundle from becoming an unhandled exception: `send_static_file` raises
    `NotFound`, and when that happens inside the 404 handler Flask has no handler left to call

    Returns:
        Response: `datagerry-app/index.html`, or MISSING_BUNDLE_MESSAGE with a 503
    """
    try:
        return app_pages.send_static_file(INDEX_FILE)
    except NotFound:
        LOGGER.error("[_send_index] %s", MISSING_BUNDLE_MESSAGE)

        return make_response(MISSING_BUNDLE_MESSAGE, MISSING_BUNDLE_STATUS)


def _names_a_file(path: str) -> bool:
    """
    Answers whether a request path names a file rather than an Angular client route

    The test is the presence of a file extension on the last segment. It is exact for this
    application: no Angular route contains a dot, and every asset the bundle references carries an
    extension

    Args:
        path (str): The request path, e.g. `/assets/logo.png` or `/objects/42`

    Returns:
        bool: True when the last path segment carries an extension
    """
    return bool(splitext(path)[1])


@app_pages.route('/')
def default_page() -> Response:
    """
    Serves the Angular SPA's `index.html` for a bare `/` request

    Anchors the SPA at the root of the dispatcher's web mount. The browser then takes over via the
    Angular router, and a later deep-link 404 is caught by `serve_spa_fallback`, so a user landing on
    `/` and a user reloading `/some/deep/route` both end up loading the same bundle

    Returns:
        Response: `datagerry-app/index.html`
    """
    return _send_index()


@app_pages.route('/favicon.ico')
def favicon() -> Response:
    """
    Answers the browser's root icon probe with the bundle's favicon

    The page declares its icons (`/assets/img/favicon-*.png` in `index.html`), but some clients still ask for
    `/favicon.ico` at the root. The file is the bundle's own `assets/img/favicon.ico`, so the binary - which ships
    the bundle and nothing else of this package - serves it too, with the bundle's asset cache lifetime. With no
    bundle built it is a 404, like every other bundle file: the fallback refuses a path with an extension

    Returns:
        Response: The bundle's `favicon.ico`
    """
    return app_pages.send_static_file(FAVICON_BUNDLE_PATH)


def serve_spa_fallback(error: HTTPException) -> Response:
    """
    SPA fallback: answers an unmatched *client route* with `index.html` (HTTP 200)

    Defined here next to the rest of the SPA-serving views but registered by `create_app` as the
    *app-level* 404 handler, so it catches unmatched URLs anywhere in this app. It does not redirect:
    it returns the bundle directly with a 200 and lets the Angular router interpret the originally
    requested path on the client.

    A path that names a file is NOT a client route, and answering one with the bundle is actively
    harmful - the caller asked for a script, an image or a stylesheet and would receive HTML with a
    success status. Those keep the 404 the router produced

    Args:
        error (HTTPException): The 404 Flask invoked the handler with. Returned unchanged for asset
            paths, which is how they keep their original status and message

    Returns:
        Response: `index.html` for a client route, or the original 404 for a path naming a file
    """
    if _names_a_file(request.path):
        return error

    return _send_index()

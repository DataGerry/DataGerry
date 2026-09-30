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
Implementation of the two routes served at the ``/rest`` root

``connection_routes`` is the ONE blueprint registered without a url_prefix (see ``init_rest_api``), so
these two live directly under ``/rest``:

* ``GET /rest/`` - a reachability probe reporting the title, version and database status
* ``GET /rest/frontend_init`` - the frontend's runtime config, read from ``app-config.json``

**Both routes are deliberately unauthenticated** - no ``insert_request_user``, no ``verify_api_access``,
no ``.protect``. That is required rather than an oversight: the Angular app fetches
``/rest/frontend_init`` to learn where the API lives *before* it can hold a token
(``runtime-config.service.ts``), and a reachability probe that needs a valid session cannot report that
the backend is unreachable. Neither response carries anything user-specific

Two things to know before changing this file:

* **``connected`` reports the truth.** An unreachable database answers **200** with
  ``connected: false``; raising out of ``dbm.status()`` would make it the
  500 below, so the one route whose job is to report connectivity could not report the negative case.
  The 500 is reserved for the route genuinely failing.
  **This route is unauthenticated and that answer is deliberate**: a caller learns "the API is up, the
  database is not". Telling an anonymous caller that much is the entire purpose of a health probe, and
  a 500 would disclose that the instance is unhealthy anyway - so this is a decision, not an oversight.
* **The database manager is resolved per request**, inside the view, like every other route module.
  Binding it at module level inside ``with current_app.app_context()`` would make importing this
  module need a live app, let the captured manager outlive the app it came from, and force a test to
  patch module state to reach it.
"""
from logging import Logger, getLogger
from typing import Any

from flask import current_app, abort
from werkzeug import Response

from cmdb.database import MongoDatabaseManager

from cmdb import __title__, __version__
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.connection_constants import ConnectionInfoKey
from cmdb.interface.rest_api.routes.connection_helper import load_frontend_config
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

connection_routes = APIBlueprint('connection_routes', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@connection_routes.route('/', methods=['GET', 'HEAD'])
def connection_test_frontend() -> Response:
    """
    Connection check for the frontend ({{url}}/rest/)

    Unauthenticated: this is the probe that answers "is the backend reachable at all", which a caller
    asks before it has a session

    ``connected`` is the real answer: **false** when the database does not respond, with a 200, so a
    monitoring check can tell "the database is down" from "the API is broken". The 500 below is for the
    latter only - a missing database manager, a serialisation failure, anything that is genuinely this
    route failing rather than the condition it exists to report

    Raises:
        HTTPException: 500 when the route itself fails; an unreachable database is ``connected: false``

    Returns:
        DefaultResponse: Dict with infos about DataGerry (title, version and database status)
    """
    try:
        # Read from the app handling THIS request, not captured at import: the probe must report the
        # state of the database the running app is configured against
        dbm: MongoDatabaseManager = current_app.database_manager

        infos: dict[str, Any] = {
            ConnectionInfoKey.TITLE.value: __title__,
            ConnectionInfoKey.VERSION.value: __version__,
            ConnectionInfoKey.CONNECTED.value: dbm.status(),
        }

        return DefaultResponse(infos).make_response()
    except Exception as err:
        # NOT the database being unreachable - that is `connected: false` above, with a 200. What
        # reaches here is the route itself failing, which is why it stays a 500 and is logged at ERROR
        LOGGER.error("[connection_test_frontend] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Could not connect to REST API!")


@connection_routes.route('/frontend_init', methods=['GET', 'HEAD'])
def frontend_init() -> Response:
    """
    Provides the frontend runtime config ({{url}}/rest/frontend_init)

    Unauthenticated by necessity: the frontend reads this to learn where the API lives, before it can
    hold a token. Returns the raw key-value pairs of the config file, unwrapped

    Degrades to an empty dict rather than failing, because the frontend falls back to its build-time
    environment when the payload is empty - a 500 here would leave it with nothing. ``Raises:`` is
    therefore absent on purpose: this route has no failure mode

    The ``except`` below is defence in depth, NOT the primary guard: ``load_frontend_config`` already
    catches a missing or malformed file itself and returns ``{}``, so nothing currently reaches here.
    It is kept so a future change to the helper's error handling cannot turn this route into a 500

    Returns:
        DefaultResponse: The frontend config as a flat dict (empty when it cannot be read)
    """
    try:
        config: dict[str, Any] = load_frontend_config()
    except Exception as err:
        LOGGER.error("[frontend_init] Exception: %s. Type: %s", err, type(err), exc_info=True)
        config = {}

    return DefaultResponse(config).make_response()

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

* **``connected`` can only ever be ``true``.** ``dbm.status()`` delegates to
  ``MongoConnector.is_connected``, which raises on every failure instead of returning False, so an
  unreachable database leaves here as a **500**, not as ``connected: false``. That is discussion-backlog
  **#141**; this route is where it is externally visible, and fixing it at the connector changes this
  route's contract.
* **The database manager is bound at IMPORT time**, at module level, rather than resolved per request
  like every other route module. It is a filed decision, not a pattern to copy.
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

# Bound ONCE when the blueprint module is first imported, which is why this needs a live app context
# here and why the manager is shared by every request. Every other route module resolves its managers
# per request through ManagerProvider; this deviation is filed as a decision, so a test that has to
# reach the manager patches this module attribute rather than a request-scoped object
with current_app.app_context():
    dbm: MongoDatabaseManager = current_app.database_manager

# -------------------------------------------------------------------------------------------------------------------- #

@connection_routes.route('/', methods=['GET', 'HEAD'])
def connection_test_frontend() -> Response:
    """
    Connection check for the frontend ({{url}}/rest/)

    Unauthenticated: this is the probe that answers "is the backend reachable at all", which a caller
    asks before it has a session

    ``connected`` is always ``true`` when the route answers - see the module docstring and
    discussion-backlog #141: an unreachable database raises out of ``dbm.status()`` and becomes the 500
    below rather than ``connected: false``. The 500 IS the negative answer

    Raises:
        HTTPException: 500 when the database status probe fails - i.e. when the database is unreachable

    Returns:
        DefaultResponse: Dict with infos about DataGerry (title, version and database status)
    """
    try:
        infos: dict[str, Any] = {
            ConnectionInfoKey.TITLE.value: __title__,
            ConnectionInfoKey.VERSION.value: __version__,
            ConnectionInfoKey.CONNECTED.value: dbm.status(),
        }

        return DefaultResponse(infos).make_response()
    except Exception as err:
        # The one condition this route exists to report, so it is logged at ERROR: at DEBUG an
        # instance whose database is unreachable answered 500 and left no trace at the default level
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

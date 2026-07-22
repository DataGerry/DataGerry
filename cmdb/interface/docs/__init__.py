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
<<<<<<< HEAD
Implementation of helper functions for the docs server
"""
from logging import Logger, getLogger
=======
Flask app that serves the Sphinx-built documentation at the dispatcher's `/docs` mount
>>>>>>> origin/version-3.2

`create_docs_server()` produces the WSGI application `WebCmdbService._run` mounts under
`/docs` inside the `DispatcherMiddleware` (alongside the SPA host at `/` and the REST API at
`/rest`). The app is intentionally narrow: register the `doc_pages` blueprint, whose static
folder points at `cmdb/interface/docs/static/` — the directory populated by `make docs`.
Without a docs build the static folder will be empty and every URL under `/docs` will 404
"""
import cmdb
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.config import app_config
from cmdb.interface.docs.doc_routes import doc_pages
# -------------------------------------------------------------------------------------------------------------------- #

<<<<<<< HEAD
LOGGER: Logger = getLogger(__name__)

=======
>>>>>>> origin/version-3.2

def create_docs_server() -> BaseCmdbApp:
    """
    Builds the Flask app that hosts the Sphinx documentation under `/docs`

    Picks the same `app_config` entry that `net_app.create_app` does (`'development'` when
    `cmdb.__MODE__ == 'DEBUG'`, otherwise `'production'`), applies it with `from_object`,
    and then writes `APPLICATION_ROOT = '/docs/'` onto *this app's* config dict — not the
    shared config class — so the sibling SPA and REST apps keep their own roots. Registers
    the `doc_pages` blueprint at `/`, which serves the `static/` Sphinx output directly;
    there is no SPA-style 404 fallback because the docs site is statically rendered

    Returns:
        BaseCmdbApp: Flask app instance, ready to be mounted under `DispatcherMiddleware`
    """
    app = BaseCmdbApp(__name__)

    app.config.from_object(app_config['development' if cmdb.__MODE__ == 'DEBUG' else 'production'])
    app.config['APPLICATION_ROOT'] = '/docs/'

    app.register_blueprint(doc_pages, url_prefix="/")

    return app

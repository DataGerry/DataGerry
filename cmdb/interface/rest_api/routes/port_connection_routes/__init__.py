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
REST API routes for the CmdbPortConnection domain

Gathers everything backing the ``/rest/port_connections`` endpoints in one place, mirroring the
``port_routes`` package:

    port_connection_routes.py           ``port_connection_blueprint`` - the CRUD endpoints
    port_connection_route_constants.py  ACL rights, request-body keys and the refusal messages
    port_connection_route_helper.py     the write guards, lookups and the duplicate-key translation

Named ``port_connection_*`` rather than ``connection_*`` deliberately: ``connection.py``,
``connection_helper.py`` and ``connection_constants.py`` already sit one level up and mean something
entirely different - whether the REST API itself is reachable (``GET /rest/``). The rights keep the
``base.framework.connection.*`` identifiers the design specified, which are unambiguous inside the
rights tree
"""
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_routes import (
    port_connection_blueprint,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'port_connection_blueprint',
]

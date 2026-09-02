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
REST API routes for the CmdbPort domain

Gathers everything backing the ``/rest/ports`` endpoints in one place, mirroring the ``rack_routes``
package:

    port_routes.py           ``port_blueprint`` - the CmdbPort CRUD endpoints
    port_route_constants.py  ACL rights, request-body keys and the refusal messages
    port_route_helper.py     the write guards and lookups every route shares
    port_object_hooks.py     what the /objects routes call when an object with ports is deleted
"""
from cmdb.interface.rest_api.routes.port_routes.port_routes import port_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'port_blueprint',
]

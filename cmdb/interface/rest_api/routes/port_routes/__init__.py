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

    port_routes.py                    ``port_blueprint`` - the CmdbPort CRUD endpoints
    port_route_constants.py           ACL rights, request-body keys and the refusal messages
    port_route_helper.py              the write guards and lookups every port route shares
    port_object_hooks.py              what the /objects routes call when an object with ports is deleted
    port_interface_link_routes.py     ``port_interface_link_blueprint`` - the port <-> IPAM interface
                                      links, mounted under the same /ports prefix the way the two rack
                                      blueprints share /racks
    port_interface_link_constants.py  request-body keys and refusal messages of those routes
    port_interface_link_helper.py     their write guards, lookups and the interface-row resolution
    port_preview_routes.py            ``port_preview_blueprint`` - the name preview, which WRITES
                                      NOTHING; step 12's bulk creation runs the same builders
    port_preview_constants.py         its request-body keys and refusal messages
    port_preview_helper.py            the one place a preview/creation request body is interpreted
    port_bulk_routes.py               ``port_bulk_blueprint`` - creating a whole device's ports in one
                                      call, with the compensating rollback
    port_bulk_helper.py               its request reading and the ordered read-back of what it created

The links carry no rights of their own: they are guarded by the PORT rights, because a link is an
attribute of a port rather than something a user manages separately
"""
from cmdb.interface.rest_api.routes.port_routes.port_routes import port_blueprint
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_routes import (
    port_interface_link_blueprint,
)
from cmdb.interface.rest_api.routes.port_routes.port_preview_routes import port_preview_blueprint
from cmdb.interface.rest_api.routes.port_routes.port_bulk_routes import port_bulk_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'port_blueprint',
    'port_interface_link_blueprint',
    'port_preview_blueprint',
    'port_bulk_blueprint',
]

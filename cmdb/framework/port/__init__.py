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
Port Connectivity logic that sits above the managers

Five things live here today:

  - the delete cascades a CmdbObject's ports, their connections and their interface links depend on
  - the interface-link resolution: a soft reference, so a dangling link is tolerated and reported
  - the name syntax generator and its preview - pure, and shared with the bulk creation, so a preview
    can never promise what the creation does differently
  - the bulk creation itself, with the compensating rollback that keeps a failed batch from leaving a
    half-built device behind
  - the connection validator: the rules a CmdbPortConnection has to satisfy that neither its document
    schema nor its indexes can express
  - the derivation of a port's `connected` flag, computed on read and never stored

The write invariants a PORT has to satisfy live in the route layer's helper instead, because they are
request-shaped (they abort). Everything here is pure and reports its result, so a write, a dry-run
pre-check, a read projection and a preview can all share it
"""
from .bulk_create import BulkCreateResult, create_batch, roll_back
from .cascade import (
    delete_connections_of_port,
    delete_connections_of_ports,
    delete_interface_links_of_port,
    delete_interface_links_of_ports,
    delete_ports_of_object,
    port_ids_of_object,
)
from .connected import collect_connected_port_ids, project_connected
from .name_preview import (
    build_face,
    build_panel_preview,
    build_standard_preview,
    preview_has_collisions,
)
from .name_syntax import (
    colliding_names,
    duplicate_names,
    generate_names,
    render_name,
    syntax_blockers,
)
from .interface_links import (
    collect_dangling_links,
    find_interface_row,
    group_links_by_interface_object,
    is_dangling,
    resolve_link_row,
)
from .connection_constants import PortConnectionError, CONNECTION_ABORT_PREFIX
from .connection_validator import (
    cable_ci_blockers,
    cable_field_blockers,
    coerce_connection_type,
    endpoint_blockers,
    missing_endpoint_blockers,
    shape_blockers,
    unknown_connection_type_blocker,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'BulkCreateResult',
    'create_batch',
    'roll_back',
    'delete_connections_of_port',
    'delete_connections_of_ports',
    'delete_interface_links_of_port',
    'delete_interface_links_of_ports',
    'delete_ports_of_object',
    'port_ids_of_object',
    'collect_dangling_links',
    'find_interface_row',
    'group_links_by_interface_object',
    'is_dangling',
    'resolve_link_row',
    'collect_connected_port_ids',
    'project_connected',
    'build_face',
    'build_panel_preview',
    'build_standard_preview',
    'preview_has_collisions',
    'colliding_names',
    'duplicate_names',
    'generate_names',
    'render_name',
    'syntax_blockers',
    'PortConnectionError',
    'CONNECTION_ABORT_PREFIX',
    'cable_ci_blockers',
    'cable_field_blockers',
    'coerce_connection_type',
    'endpoint_blockers',
    'missing_endpoint_blockers',
    'shape_blockers',
    'unknown_connection_type_blocker',
]

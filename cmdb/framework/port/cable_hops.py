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
Reading one hop of the physical layer

Two pure questions every consumer of the cabling asks: which port is at the other end of a connection,
and which of an object's cables lead somewhere else. They live here rather than with either caller
because both the CI Explorer's connection source and the cabling view ask them of the same documents,
and neither may import the other - one is a framework source, the other a route helper.

An INTERNAL pairing is never a hop: it joins two ports of ONE object, so it leads nowhere a graph can
draw. Neither is a cable whose far end is another port of the object it started on
"""
from typing import Any

from cmdb.models.port_connection_model.port_connection_constants import ConnectionType, PortConnectionKey
# -------------------------------------------------------------------------------------------------------------------- #

def other_endpoint(connection: dict[str, Any] | None, port_id: int) -> int | None:
    """
    Returns the endpoint of a connection that is not the given port

    ``endpoints`` is stored sorted, so a fixed position means nothing: the question can only ever be
    asked as membership. A self-connection (both endpoints equal) answers None, since it leads nowhere

    Args:
        connection (dict[str, Any] | None): The CmdbPortConnection document, or None when the port
            carries none
        port_id (int): The endpoint the edge is seen from

    Returns:
        int | None: The far endpoint, or None when the connection does not name exactly one other port
    """
    endpoints: list[Any] = (connection or {}).get(PortConnectionKey.ENDPOINTS.value) or []
    far_endpoints: list[int] = [
        endpoint for endpoint in endpoints if isinstance(endpoint, int) and endpoint != port_id
    ]

    return far_endpoints[0] if len(far_endpoints) == 1 else None


def collect_cable_hops(
        connections: list[dict[str, Any]],
        focal_port_ids: set[int]) -> list[tuple[dict[str, Any], int]]:
    """
    Pairs every cable of the focal object with the port at its far end

    Only CABLE connections are read. An INTERNAL pairing joins two ports of one object and would be a
    self-loop, and so would a cable whose far end is another port of the focal object (Q39) - both are
    skipped here rather than filtered out afterwards, so neither reaches the far-side read.

    One connection yields one entry, which is what makes two objects cabled together twice two edges
    rather than one (Q36)

    Args:
        connections (list[dict[str, Any]]): The connections of the focal object's ports
        focal_port_ids (set[int]): public_ids of the focal object's own ports

    Returns:
        list[tuple[dict[str, Any], int]]: Each cable with the port public_id at its far end
    """
    hops: list[tuple[dict[str, Any], int]] = []

    for connection in connections:
        if connection.get(PortConnectionKey.CONNECTION_TYPE.value) != ConnectionType.CABLE.value:
            continue

        near_port_id: int | None = next(
            (endpoint for endpoint in connection.get(PortConnectionKey.ENDPOINTS.value) or []
             if endpoint in focal_port_ids),
            None,
        )

        if near_port_id is None:
            continue

        far_port_id: int | None = other_endpoint(connection, near_port_id)

        if far_port_id is None or far_port_id in focal_port_ids:
            continue

        hops.append((connection, far_port_id))

    return hops

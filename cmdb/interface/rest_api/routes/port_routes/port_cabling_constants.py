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
Response shape of the cabling view

One ring of the physical layer: the focal CmdbObject, every object a cable of its reaches, and the
cables between them. The client draws it as a graph and follows the cabling outwards by asking for the
next object - so a node carries everything needed both to RENDER it and to expand from it.

The keys live here rather than in ``port_overview_constants`` because this is a different view of the
same data: the overview answers "this object's ports as a table", this answers "this object and its
neighbourhood as a graph". The per-port rows inside a node are the overview's, reused unchanged.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# What the route's error tail calls the thing it was building when it failed
PORT_CABLING_SUBJECT: str = 'the cabling view'


class PortCablingKey(BaseStrEnum):
    """
    Top-level keys of the ``/ports/object/<object_id>/cabling`` response

    FOCAL_OBJECT_ID names which of the NODES the view opened on - the client needs it to centre the
    graph, and every other node in the answer is one cable away from it. EDGES is redundant with the
    nodes' own port rows and exists anyway: it is what the canvas draws, and it pairs the two ends of
    each cable once so the client does not have to match them up and de-duplicate
    """
    FOCAL_OBJECT_ID = 'focal_object_id'
    NODES = 'nodes'
    EDGES = 'edges'


class CablingNodeKey(BaseStrEnum):
    """
    Keys of one node of the cabling graph

    TITLE and TYPE_INFO are built by the CI Explorer's own composers, so an object looks the same in
    both graphs. DEVICE_KIND and ROWS are the ports overview's, unchanged - which is what makes a
    patch panel render as front/rear pairs here too.

    PORT_COUNT counts PORTS, where ``len(rows)`` counts rows: a panel's row is a front/rear pair, so
    the two differ by a factor of two on exactly the objects where the badge matters most.

    RESTRICTED marks a neighbour the requesting user may not read. Such a node carries its id and
    nothing else - the cable that reaches it is visible to a user who may read this object's ports,
    but what sits at the far end is not
    """
    OBJECT_ID = 'object_id'
    TITLE = 'title'
    TYPE_INFO = 'type_info'
    DEVICE_KIND = 'device_kind'
    PORT_COUNT = 'port_count'
    ROWS = 'rows'
    RESTRICTED = 'restricted'


class CablingEdgeKey(BaseStrEnum):
    """
    Keys of one edge of the cabling graph - exactly one CmdbPortConnection

    FROM_END and TO_END are ordered by the stored ``endpoints`` pair, which is sorted ascending, so
    one cable always produces the same edge whichever of its two objects the view opened on. CABLE is
    the resolved block every connection read answers with, and it is what the edge is labelled by
    """
    CONNECTION_ID = 'connection_id'
    FROM_END = 'from'
    TO_END = 'to'
    CABLE = 'cable'


class CablingEndKey(BaseStrEnum):
    """
    Keys of one end of an edge: which port of which object the cable lands on

    Enough to draw the edge between two port rows rather than between two node boxes, which is what
    the mockup's lines do
    """
    OBJECT_ID = 'object_id'
    PORT_ID = 'port_id'
    PORT_NAME = 'port_name'
    SIDE = 'side'

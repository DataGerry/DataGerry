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
Response shape of the ports overview

The overview answers one object's ports in the shape its panel renders them, which is not the shape
they are stored in: a patch panel is shown one row per front/rear PAIR, an ordinary device one row per
port. ``DEVICE_KIND`` is what tells the two apart, so a reader never has to infer it from the rows.

The keys live here rather than in ``port_route_constants`` because they name a view that nothing else
produces - the stored port keys are ``PortKey``, and this response deliberately does not repeat them.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# What the route's error tail calls the thing it was building when it failed
PORT_OVERVIEW_SUBJECT: str = 'the Ports overview'


class PortOverviewKey(BaseStrEnum):
    """
    Top-level keys of the ``/ports/object/<object_id>/overview`` response

    DEVICE_KIND is a ``PortDeviceKind`` value, or None for an object that holds no ports at all -
    such an object is still free to become either kind, so naming one would be a guess. It decides
    which row shape ROWS carries (see PortOverviewRowKey), and an object can never be both: the port
    write guards refuse a port of the other kind while any port exists
    """
    DEVICE_KIND = 'device_kind'
    ROWS = 'rows'
    TOTAL = 'total'


class PortOverviewRowKey(BaseStrEnum):
    """
    Keys of one overview row

    Two shapes, chosen by the response's DEVICE_KIND:

      - STANDARD: PORT alone - one row per port
      - PATCH_PANEL: FRONT and REAR - one row per pairing, either of which may be None. A face whose
        counterpart was never paired is still listed, with the other slot empty: a half-built panel
        has to be visible to be fixable

    PAIRED reports whether an INTERNAL connection actually joins the two, which is what makes an
    unpaired face legible as such instead of leaving it to be inferred from an empty slot
    """
    PORT = 'port'
    FRONT = 'front'
    REAR = 'rear'
    PAIRED = 'paired'


class PortOverviewEntryKey(BaseStrEnum):
    """
    Keys of one port inside an overview row

    The three select fields are resolved to {id, label} pairs (see PortOverviewOptionKey) so the panel
    needs no extendable-option catalog of its own. CABLE is the resolved cable block every connection
    read answers with, CONNECTED_PORT and CONNECTED_OBJECT the two halves of the far end - the port the
    cable lands on and the CI owning it, which is how a connection is named to a user: port first, then
    device. INTERFACE_LINKS carries the links exactly as the port reads do - their rows are summarised
    by the client, which owns how an interface is named
    """
    PORT_ID = 'port_id'
    SIDE = 'side'
    PORT_NUMBER = 'port_number'
    NAME = 'name'
    STATUS = 'status'
    PORT_TYPE = 'port_type'
    SPEED = 'speed'
    DESCRIPTION = 'description'
    CONNECTED = 'connected'
    CABLE = 'cable'
    CABLE_CONNECTION_ID = 'cable_connection_id'
    CONNECTED_PORT = 'connected_port'
    CONNECTED_OBJECT = 'connected_object'
    INTERFACE_LINKS = 'interface_links'


class PortOverviewOptionKey(BaseStrEnum):
    """
    Keys of a resolved select value

    ID is the stored ``CmdbExtendableOption`` public_id, which an edit form needs to preselect the
    option; LABEL is what the user picked it by. A stored id whose option is gone keeps its ID and
    answers a LABEL of None - dropping the id would silently rewrite the port's stored value
    """
    ID = 'id'
    LABEL = 'label'


class ConnectedPortKey(BaseStrEnum):
    """
    Keys of the port at the other end of a cable

    Enough to name that end without reading it again: the connection dialog renders it as
    ``<name> (<side>) - <object label>``, and an action on the far port needs its id. SIDE is a
    PortSide value, so a far end on a panel face can be labelled as one.

    NAME and SIDE are None when the port's owner is one the requesting user may not read - the single
    port read answers 403 for that port, so this response may not hand its name out either. PORT_ID
    stays: the connection the user is allowed to read already names it
    """
    PORT_ID = 'port_id'
    NAME = 'name'
    SIDE = 'side'


class ConnectedObjectKey(BaseStrEnum):
    """
    Keys of the CI at the other end of a port's cable

    One cable hop, never a chain: the connected CI is the owner of the port this cable ends on, so a
    device cabled into a patch panel reports the panel. RESTRICTED marks an object the requesting user
    may not read - its id is what the port's own connection already reveals, but its LABEL is withheld
    rather than composed from a document the user has no access to
    """
    OBJECT_ID = 'object_id'
    LABEL = 'label'
    RESTRICTED = 'restricted'

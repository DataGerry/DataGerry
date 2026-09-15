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
Whether a CmdbPort is connected - derived on read, never stored

A stored flag would be a second truth about something the connections collection already answers, and
a derived value that can go stale is worse than a cheap one that cannot: every write path that creates,
moves or removes a connection would have to remember to update it, and the one that forgot would leave
a port reading 'Free' with a cable in it.

**The subtlety this module exists for.** A connection stores its two endpoints in one array, sorted
ascending, so a given port is sometimes the first element and sometimes the second - which of the two
is an accident of the ids the user happened to pick. Anything that looked at one position only would
report roughly half of all connected ports as free, and no test using a single fixed pair would notice.
Membership in the array is therefore the only question asked here.

Pure and free of Flask and of managers: the routes perform the one batched read and hand the result
in, so this can be exercised over a stubbed connection set. What it does NOT do is resolve the peer -
per Q21 this step returns the boolean and nothing else, and whether the ports list names the port at
the other end is discussion backlog #195
"""
from logging import Logger, getLogger
from typing import Any, Iterable

from cmdb.models.port_connection_model.port_connection_constants import PortConnectionKey
from cmdb.models.port_model.port_constants import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def collect_connected_port_ids(connections: Iterable[dict[str, Any]]) -> set[int]:
    """
    Returns every CmdbPort public_id that appears in any of the given connections

    Both endpoints of every connection are collected, because the pair is sorted and neither position
    carries meaning - a port that is the second element of one connection is just as connected as one
    that is the first

    Args:
        connections (Iterable[dict[str, Any]]): The CmdbPortConnection documents to read

    Returns:
        set[int]: The public_ids of the ports these connections touch, empty when there are none
    """
    connected_ids: set[int] = set()

    for connection in connections:
        endpoints: Any = connection.get(PortConnectionKey.ENDPOINTS.value)

        if not isinstance(endpoints, (list, tuple)):
            continue

        connected_ids.update(endpoint for endpoint in endpoints if isinstance(endpoint, int))

    return connected_ids


def project_connected(
        ports: list[dict[str, Any]],
        connections: Iterable[dict[str, Any]],
        connected_key: str) -> list[dict[str, Any]]:
    """
    Adds the derived connected flag to every port of a response

    The ports are mutated in place and returned, which is what the routes want - the documents came
    straight out of the manager and are about to be serialised, so copying them would only cost a
    second dict per port on a path that runs for every ports panel.

    Every port receives the key, including the free ones: a response where 'connected' is present on
    some rows and absent on others would make the frontend distinguish 'free' from 'unknown', and there
    is no such state

    Args:
        ports (list[dict[str, Any]]): The port documents to annotate
        connections (Iterable[dict[str, Any]]): The connections touching those ports, read in one
            batched query by the caller
        connected_key (str): The response key to write the flag under. Passed in rather than imported,
            because it is a RESPONSE key and deliberately not a member of PortKey - there is no such
            field on a stored port

    Returns:
        list[dict[str, Any]]: The same port documents, each carrying the flag
    """
    connected_ids: set[int] = collect_connected_port_ids(connections)

    for port in ports:
        port[connected_key] = port.get(PortKey.PUBLIC_ID.value) in connected_ids

    return ports

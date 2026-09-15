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
Which Cable CIs a CmdbPortConnection still needs, and what that refuses

A `CABLE` connection is the fact that two ports are patched together; the Cable CI is an OPTIONAL
description of the physical cable (a connection carries the five inline `cable_*` values, or a
`cable_ci_id`, or neither). So the connection does not depend on the CI - which is exactly why
deleting the CI may not delete the connection:

* the patch is still there physically. A connection removed because someone deleted an inventory
  record would make the CMDB claim two ports are unconnected
* it is the least recoverable direction. Re-creating a connection needs the two port ids, which is
  the information the deletion would destroy; re-creating a cable record needs a name

Compare the two cascades the feature does have: deleting a **port** deletes its connections (a
connection cannot exist without two ports) and deleting an **interface row** leaves its link intact
(a soft reference, reported and never cascaded). The Cable CI belongs to the second kind - but where
a dangling interface row is merely reported, a dangling `cable_ci_id` also leaves the connection
unable to describe its cable at all (inline values and a CI are mutually exclusive). So the deletion
is **refused** instead: the user resolves the connection, or edits it to describe the cable inline -
and there they can pick the right cable type from the option list, which an automatic adoption could
only guess at (a CI stores the type's LABEL, a connection its option id - discussion-backlog #196)

Pure: the read happens in the caller and its result is passed in, so both the refusal and its message
are unit-testable without a request. One batched query answers a whole bulk delete
"""
from logging import Logger, getLogger
from typing import Any, NamedTuple

from cmdb.manager.port_connections_manager import PortConnectionsManager

from cmdb.models.port_connection_model import PortConnectionKey

from cmdb.framework.port.connection_constants import (
    CABLE_IN_USE_ABORT_PREFIX,
    CABLE_IN_USE_MESSAGE,
    CABLE_IN_USE_SEPARATOR,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CableUsage',
    'cable_usage_blocker',
    'collect_cable_usage',
]

LOGGER: Logger = getLogger(__name__)


class CableUsage(NamedTuple):
    """One Cable CI and the CmdbPortConnection that uses it"""
    cable_ci_id: int
    connection_id: int
    endpoints: list[int]


def collect_cable_usage(
        port_connections_manager: PortConnectionsManager,
        cable_ci_ids: list[int]) -> list[CableUsage]:
    """
    Reports which of the given Cable CIs a CmdbPortConnection still uses

    One query for the whole list, so a bulk delete of many objects costs the same as a single one.
    A cable can appear at most once: `cable_ci_id` carries a partial unique index

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        cable_ci_ids (list[int]): public_ids of the CABLE SpecialType CmdbObjects to check

    Raises:
        PortConnectionsManagerGetError: If the connections could not be read

    Returns:
        list[CableUsage]: One entry per used Cable CI, ordered by the cable's public_id
    """
    if not cable_ci_ids:
        return []

    connections: list[dict[str, Any]] = port_connections_manager.get_connections_by_cable_cis(cable_ci_ids)
    usages: list[CableUsage] = []

    for connection in connections:
        cable_ci_id: Any = connection.get(PortConnectionKey.CABLE_CI_ID.value)
        connection_id: Any = connection.get(PortConnectionKey.PUBLIC_ID.value)

        if not isinstance(cable_ci_id, int) or not isinstance(connection_id, int):
            # A connection the query matched on its cable_ci_id but that carries no usable ids is a
            # broken row; reporting it would name nothing the user could act on
            LOGGER.warning("[collect_cable_usage] Skipping a Port connection without usable ids: %r",
                           connection)
            continue

        usages.append(CableUsage(
            cable_ci_id=cable_ci_id,
            connection_id=connection_id,
            endpoints=list(connection.get(PortConnectionKey.ENDPOINTS.value) or []),
        ))

    return sorted(usages, key=lambda usage: usage.cable_ci_id)


def cable_usage_blocker(usages: list[CableUsage]) -> str | None:
    """
    Builds the refusal for a deletion that would strand a CmdbPortConnection's cable

    Every blocked cable is named with the connection that uses it and that connection's two ports, so
    the message says what to act on rather than only that something is in the way. A bulk delete is
    refused as a whole, so all of them are listed

    Args:
        usages (list[CableUsage]): The Cable CIs still in use, from `collect_cable_usage`

    Returns:
        str | None: The refusal message, or None when nothing is in use
    """
    if not usages:
        return None

    reasons: str = CABLE_IN_USE_SEPARATOR.join(
        CABLE_IN_USE_MESSAGE.format(
            cable_ci_id=usage.cable_ci_id,
            connection_id=usage.connection_id,
            port_ids=', '.join(str(port_id) for port_id in usage.endpoints),
        )
        for usage in usages
    )

    return f'{CABLE_IN_USE_ABORT_PREFIX}: {reasons}!'

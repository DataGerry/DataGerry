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
What happens to a CmdbObject's ports when the object itself is deleted

A port belongs to exactly one CmdbObject and is stored outside that object's document, so nothing
removes it when the object goes: without this cascade every deleted object would leave its ports
behind as rows nothing can reach or clean up.

The connections half is NOT here yet - framework.portConnections does not exist. The step that adds
it has to extend this cascade, or a deleted object leaves dangling connections whose endpoint no
longer resolves
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.ports_manager import PortsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def delete_ports_of_object(ports_manager: PortsManager, deleted_object: dict[str, Any]) -> int:
    """
    Removes every CmdbPort a deleted CmdbObject owned

    One statement, not a per-port loop. An object that never had ports is a no-op costing a single
    indexed delete. Whether the object's type declares `uses_ports` is deliberately NOT consulted: the
    flag can have been turned off after the ports were created, and the rows would then be orphaned by
    exactly the check meant to protect them

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        deleted_object (dict[str, Any]): The CmdbObject document that was (or is about to be) deleted

    Returns:
        int: The number of removed ports
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return 0

    removed: int = ports_manager.delete_ports_of_object(object_id)

    if removed:
        LOGGER.info(
            "[delete_ports_of_object] CmdbObject ID:%s deleted - removed %s port(s)", object_id, removed,
        )

    return removed

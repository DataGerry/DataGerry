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
The Port consequences of a CmdbObject write, called from the /objects routes

The object routes own the object lifecycle; this module is what they call so a deleted object does not
leave its ports behind. It mirrors rack_object_hooks: the hook resolves the managers it needs and
delegates the actual statement to cmdb.framework.port, so the cascade itself stays testable without a
request
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.user_model import CmdbUser

from cmdb.framework.port.cascade import delete_ports_of_object
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def handle_object_deleted(request_user: CmdbUser, deleted_object: dict[str, Any]) -> None:
    """
    Removes the ports a deleted CmdbObject leaves behind

    Not gated on the licence or on the type's `uses_ports` flag, deliberately: cleanup must never be
    blocked by a state the user cannot currently reach. A licence that lapsed, or a flag turned off
    after the ports were created, would otherwise orphan exactly the rows this exists to remove. The
    same reasoning the Rack hooks apply to their own cleanup

    Args:
        request_user (CmdbUser): The user performing the deletion
        deleted_object (dict[str, Any]): The CmdbObject document being deleted
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return

    ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

    delete_ports_of_object(ports_manager, deleted_object)

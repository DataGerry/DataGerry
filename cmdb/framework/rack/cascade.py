# DATAGERRY - OpenSource Enterprise CMDB
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
What happens to rack memberships when a CmdbObject is deleted

A mount row references two objects, and either of them going away leaves it dangling:

  - **the Rack is deleted** -> every membership of that rack goes, and the mounted objects survive
    untouched. Deleting a rack means the rack is gone, not the devices that were in it
  - **a mounted object is deleted** -> its own membership goes, and the rack survives with a free slot

Both are one statement, not a per-row loop. The location side of the same events lives in the route layer
(rack_location_helper), because it needs the object<->location mirror helpers that live there
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey

from cmdb.framework.rack.enforcement import is_rack_object
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def delete_rack_memberships(
        types_manager: TypesManager,
        rack_mounts_manager: RackMountsManager,
        deleted_object: dict[str, Any]) -> int:
    """
    Removes every rack membership a deleted CmdbObject was involved in

    Handles both roles in one call, because the caller deleting an object does not need to care which one
    it was: a Rack loses all of its memberships, any other object loses the one membership it could have
    had. An object that is neither is a no-op and costs a single indexed read

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        rack_mounts_manager (RackMountsManager): db interface for CmdbRackMounts
        deleted_object (dict[str, Any]): The CmdbObject document that was (or is about to be) deleted

    Returns:
        int: The number of removed mount rows
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return 0

    if is_rack_object(types_manager, deleted_object):
        removed: int = rack_mounts_manager.delete_mounts_of_rack(object_id)

        if removed:
            LOGGER.info("[delete_rack_memberships] Rack ID:%s deleted - removed %s membership(s); the "
                        "mounted objects were not touched", object_id, removed)

        return removed

    return rack_mounts_manager.delete_mount_of_object(object_id)

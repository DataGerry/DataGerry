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
What a location parent means for the Rack feature, resolved once per write

A location parent that is a Rack's own node means membership of that Rack. Which Rack that is, whether the caller may
change it and whether the licence allows joining one depend on the parent alone - not on the object being placed - so
a write resolves them once and hands the result from the check before the write to the reconcile after it, and a batch
move shares it across every object it moves. Kept free of manager imports so the object write context can carry it
"""
from dataclasses import dataclass, field
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass
class RackLocationTarget:
    """
    The Rack a location parent stands for, and the decisions about Racks already taken for the write

    Attributes:
        requested_parent (int | None): public_id of the CmdbLocation the write asks for, None when cleared
        rack (dict[str, Any] | None): The Rack CmdbObject owning that node, None when the node is no Rack's
        write_blockers (dict[int, str | None]): Rack public_id -> why the caller may not change that Rack, or None
            when it may; filled as Racks are judged, so a batch judges each Rack once
        licence_checked (bool): Whether the licence for joining a Rack was already checked for this write
    """
    requested_parent: int | None
    rack: dict[str, Any] | None
    write_blockers: dict[int, str | None] = field(default_factory=dict)
    licence_checked: bool = False

    @property
    def rack_id(self) -> int | None:
        """
        The public_id of the Rack the parent stands for

        Returns:
            int | None: The Rack's public_id, None when the parent is no Rack's node
        """
        return self.rack.get(CmdbObjectKey.PUBLIC_ID.value) if self.rack else None

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
Areas and document keys of a CmdbRackMount
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class RackArea(BaseStrEnum):
    """
    Where in a Rack a mounted CmdbObject sits

    The three MAIN areas carry slot geometry (a start slot and a height in U, the start slot being the
    mount's topmost occupied U since a mount extends downward); the two SIDE areas are
    plain ordered lists with no geometry at all. UNASSIGNED is membership without placement: the object
    belongs to the Rack but sits nowhere in it yet - which is also where an object lands when the Rack
    is shrunk below its slots.

    FULL_DEPTH is a mount deep enough to occupy the same U range in the front AND the back view, so it
    conflicts with both (see get_conflicting_areas)
    """
    FRONT = 'FRONT'
    BACK = 'BACK'
    FULL_DEPTH = 'FULL_DEPTH'
    LEFT = 'LEFT'
    RIGHT = 'RIGHT'
    UNASSIGNED = 'UNASSIGNED'


    @classmethod
    def get_main_areas(cls) -> frozenset["RackArea"]:
        """
        Returns the areas that carry slot geometry

        These are the areas a start slot and a height are required for, and the only ones an overlap
        check applies to

        Returns:
            frozenset[RackArea]: The front, back and full-depth areas
        """
        return frozenset({cls.FRONT, cls.BACK, cls.FULL_DEPTH})


    @classmethod
    def get_side_areas(cls) -> frozenset["RackArea"]:
        """
        Returns the areas that are plain ordered lists

        Side mounts carry no geometry - only membership and an order index

        Returns:
            frozenset[RackArea]: The left and right areas
        """
        return frozenset({cls.LEFT, cls.RIGHT})


    @classmethod
    def get_ordered_areas(cls) -> frozenset["RackArea"]:
        """
        Returns the areas whose members are kept in an explicit order

        Both side lists and the unassigned bucket have no geometry to sort by, so they carry a
        position index instead

        Returns:
            frozenset[RackArea]: The side areas plus UNASSIGNED
        """
        return cls.get_side_areas() | {cls.UNASSIGNED}


    @classmethod
    def get_conflicting_areas(cls, area: "RackArea") -> frozenset["RackArea"]:
        """
        Returns the areas whose U ranges a mount in the given area competes for

        A FRONT mount competes with other FRONT mounts and with FULL_DEPTH ones; the same holds for
        BACK. A FULL_DEPTH mount competes with everything in the main areas, because it occupies the
        same U range in both views. Side and unassigned mounts compete for nothing

        Args:
            area (RackArea): The area a mount is being placed in

        Returns:
            frozenset[RackArea]: Every area to check for an overlapping U range
        """
        if area == cls.FULL_DEPTH:
            return cls.get_main_areas()

        if area in (cls.FRONT, cls.BACK):
            return frozenset({area, cls.FULL_DEPTH})

        return frozenset()


class RackMountKey(BaseStrEnum):
    """Document field names of a CmdbRackMount (collection ``framework.rackMounts``)"""
    PUBLIC_ID = 'public_id'
    RACK_ID = 'rack_id'
    OBJECT_ID = 'object_id'
    AREA = 'area'
    START_SLOT = 'start_slot'
    HEIGHT = 'height'
    POSITION = 'position'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'

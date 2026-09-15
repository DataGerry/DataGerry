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
Areas, kinds and document keys of a CmdbRackMount
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class RackMountKind(BaseStrEnum):
    """
    What a row in a Rack represents

    A MOUNT names a CmdbObject; the two OCCUPANT kinds name none - they hold space. All three share one
    document shape and one set of geometry rules, because a reservation and a blocker occupy a U range
    exactly the way a mount does and take part in the same overlap check. The kinds exist so the grid
    can draw them differently and so the per-kind field rules can be stated:

      - MOUNT - a CmdbObject in the rack. Requires an object_id, carries no reservation fields
      - RESERVATION - space held for hardware that will arrive later. May carry a date range and a
        colour, and may cover several future devices, so it is never converted into a mount in place
      - BLOCKER - space that can not be mounted at all, e.g. a metal frame between rack sections
    """
    MOUNT = 'MOUNT'
    RESERVATION = 'RESERVATION'
    BLOCKER = 'BLOCKER'


    @classmethod
    def get_occupant_kinds(cls) -> frozenset["RackMountKind"]:
        """
        Returns the kinds that hold space without naming a CmdbObject

        These are the rows that must NOT carry an object_id, are never mirrored into the location tree,
        and are excluded from anything keyed on the mounted object

        Returns:
            frozenset[RackMountKind]: The reservation and blocker kinds
        """
        return frozenset({cls.RESERVATION, cls.BLOCKER})


    @classmethod
    def is_occupant(cls, kind: str | None) -> bool:
        """
        Reports whether a stored kind value is one of the occupant kinds

        Tolerates an unknown or missing value by answering False: a row whose kind did not survive is
        treated as a MOUNT, which is what every row written before the kinds existed is

        Args:
            kind (str | None): The row's stored kind value

        Returns:
            bool: True when the row holds space rather than a CmdbObject
        """
        return kind in {member.value for member in cls.get_occupant_kinds()}


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
    """
    Document field names of a CmdbRackMount (collection ``framework.rackMounts``)

    KIND is on every row. OBJECT_ID is on MOUNT rows only - an occupant OMITS it rather than storing
    null, which is what lets the unique index be partial on the kind. LABEL is free text on any row;
    START_DATE, END_DATE and COLOR belong to a RESERVATION alone
    """
    PUBLIC_ID = 'public_id'
    RACK_ID = 'rack_id'
    OBJECT_ID = 'object_id'
    KIND = 'kind'
    LABEL = 'label'
    START_DATE = 'start_date'
    END_DATE = 'end_date'
    COLOR = 'color'
    AREA = 'area'
    START_SLOT = 'start_slot'
    HEIGHT = 'height'
    POSITION = 'position'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'

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
This module contains the implementation of CmdbRackMount, a row occupying space in a Rack
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from dateutil.parser import parse

from cmdb.utils.helpers import coerce_datetime

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey, RackMountKind
from cmdb.models.rack_model.rack_mount_helpers import occupied_slots_of

from cmdb.class_schema.rack_model.cmdb_rack_mount_schema import get_cmdb_rack_mount_schema

from cmdb.errors.models.cmdb_rack_mount import (
    CmdbRackMountInitError,
    CmdbRackMountInitFromDataError,
    CmdbRackMountToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbRackMount - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbRackMount(CmdbDAO):
    """
    A CmdbRackMount is one row occupying space in a Rack

    A MOUNT row binds one CmdbObject to the rack: the document's EXISTENCE is the object's membership,
    its GEOMETRY is the placement, and the geometry is optional - an UNASSIGNED mount is a member
    sitting nowhere yet. The row is the single authority on both: the rack view, the location tree and
    the CI-Explorer are all projections of it, never the other way round.

    A RESERVATION or BLOCKER row names no CmdbObject; it holds space. Same document, same geometry
    rules, same overlap check - only the kind and what the grid draws differ. An occupant is never
    mirrored into the location tree, because the tree mirrors CmdbObjects.

    Which geometry keys an area requires and whether a placement collides is enforced by
    cmdb.framework.rack.mount_validator; which fields a kind may carry, by
    cmdb.framework.rack.occupant_validator. Neither is expressible in the document schema, which can
    only describe shape per field

    `Extends`: CmdbDAO
    """
    COLLECTION = 'framework.rackMounts'
    MODEL = 'RackMount'
    # object_id is deliberately absent: an occupant row has none. That a MOUNT requires one is a
    # per-kind rule, checked by the occupant validator where the kind is known
    REQUIRED_INIT_KEYS: list[str] = ['rack_id', 'area']

    INDEX_KEYS: list[dict[str, Any]] = [
        # An object belongs to at most one rack, and only once - the UNASSIGNED bucket counts as
        # membership, so this also stops an object being unplaced in one rack and placed in another.
        # This index is the actual guarantee; nothing else enforces it.
        #
        # Partial because an occupant row OMITS object_id, and a unique index treats every missing
        # value as the same null - without the filter the second occupant in the whole collection would
        # be refused with a duplicate-key error.
        #
        # The filter is the field's PRESENCE rather than kind == MOUNT, which is the stricter of the
        # two: it also covers a row written before the kinds existed (such a row has an object_id but
        # no kind, and a kind-based filter would quietly stop guaranteeing anything for it). It relies
        # on the occupant row omitting the key rather than storing null - which build_mount_candidate
        # does, and the update path re-asserts only when the key is already there
        {
            'keys': [('object_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'object_id',
            'unique': True,
            'partialFilterExpression': {'object_id': {'$exists': True}},
        },
        {'keys': [('rack_id', CmdbDAO.DAO_ASCENDING)], 'name': 'rack_id', 'unique': False},
        # Every read of a rack is "one rack, one area": the overview's buckets and the overlap check
        # both filter on exactly this pair, so it is served from one index instead of a rack-wide scan
        {
            'keys': [
                ('rack_id', CmdbDAO.DAO_ASCENDING),
                ('area', CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'rack_area',
            'unique': False
        },
    ]

    SCHEMA: dict = get_cmdb_rack_mount_schema()


    #pylint: disable=R0913, R0914, R0917
    def __init__(
            self,
            public_id: int,
            rack_id: int,
            area: str,
            object_id: int | None = None,
            kind: str = RackMountKind.MOUNT.value,
            label: str | None = None,
            start_date: datetime | None = None,
            end_date: datetime | None = None,
            color: str | None = None,
            start_slot: int | None = None,
            height: int | None = None,
            position: int | None = None,
            author_id: int | None = None,
            creation_time: datetime = None,
            last_edit_time: datetime = None):
        """
        Initialises a CmdbRackMount

        Args:
            public_id (int): public_id of the CmdbRackMount
            rack_id (int): public_id of the Rack CmdbObject the row belongs to
            area (str): A RackArea value - where in the rack the row sits
            object_id (int | None): public_id of the mounted CmdbObject; None on an occupant row,
                                    which holds space without naming an object
            kind (str): A RackMountKind value. Defaults to MOUNT, which is also what a row written
                        before the kinds existed reads as
            label (str | None): Free text shown on the row, e.g. 'Reserved for DB cluster'
            start_date (datetime | None): Start of a reservation's period. Purely descriptive - it
                                          never affects whether the row blocks its slots
            end_date (datetime | None): End of a reservation's period, equally descriptive
            color (str | None): A reservation's '#RRGGBB' colour; None lets the frontend choose
            start_slot (int | None): The U the mount is anchored at - its TOPMOST occupied slot,
                                     since a mount extends downward; None for a side or unassigned mount
            height (int | None): Occupied U count; None for a side mount, retained as a hint when
                                 an object is unplaced so re-placing can pre-fill it
            position (int | None): Order index within a side list or the unassigned bucket
            author_id (int | None): public_id of the CmdbUser who created the mount
            creation_time (datetime, optional): When the mount was created. Defaults to now
            last_edit_time (datetime, optional): When the mount was last changed. Defaults to None

        Raises:
            CmdbRackMountInitError: If the CmdbRackMount could not be initialised
        """
        try:
            self.rack_id: int = rack_id
            self.object_id: int | None = object_id
            self.kind: str = kind
            self.label: str | None = label
            self.start_date: datetime | None = start_date
            self.end_date: datetime | None = end_date
            self.color: str | None = color
            self.area: str = area
            self.start_slot: int | None = start_slot
            self.height: int | None = height
            self.position: int | None = position
            self.author_id: int | None = author_id
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)
            self.last_edit_time: datetime | None = last_edit_time

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbRackMountInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbRackMount":
        """
        Initialises a CmdbRackMount from a dict

        Args:
            data (dict): Data with which the CmdbRackMount should be initialised

        Raises:
            CmdbRackMountInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbRackMount: CmdbRackMount with the given data
        """
        try:
            creation_time = data.get('creation_time', None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time = data.get('last_edit_time', None)

            if last_edit_time and isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id = data.get('public_id'),
                rack_id = data.get('rack_id'),
                object_id = data.get('object_id'),
                kind = data.get('kind', RackMountKind.MOUNT.value),
                label = data.get('label'),
                start_date = coerce_datetime(data.get('start_date')),
                end_date = coerce_datetime(data.get('end_date')),
                color = data.get('color'),
                area = data.get('area'),
                start_slot = data.get('start_slot'),
                height = data.get('height'),
                position = data.get('position'),
                author_id = data.get('author_id'),
                # The audit timestamps parse strictly: an unusable one surfaces as the model's own
                # error rather than silently becoming "now". The reservation dates above are lenient
                # instead, because the routes refuse an unusable one with a readable 400 before it is
                # ever stored
                creation_time = creation_time,
                last_edit_time = last_edit_time,
            )
        except Exception as err:
            raise CmdbRackMountInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbRackMount") -> dict:
        """
        Converts a CmdbRackMount into a json compatible dict

        Args:
            instance (CmdbRackMount): The CmdbRackMount which should be converted

        Raises:
            CmdbRackMountToJsonError: If the CmdbRackMount could not be converted

        Returns:
            dict: Json compatible dict of the CmdbRackMount values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'rack_id': instance.rack_id,
                'object_id': instance.object_id,
                'kind': instance.kind,
                'label': instance.label,
                'start_date': instance.start_date,
                'end_date': instance.end_date,
                'color': instance.color,
                'area': instance.area,
                'start_slot': instance.start_slot,
                'height': instance.height,
                'position': instance.position,
                'author_id': instance.author_id,
                'creation_time': instance.creation_time,
                'last_edit_time': instance.last_edit_time,
            }
        except Exception as err:
            raise CmdbRackMountToJsonError(err) from err

# ------------------------------------------------ GENERAL FUNCTIONS ------------------------------------------------- #

    def is_placed(self) -> bool:
        """
        Reports whether the mount has a placement, as opposed to being a bare membership

        Returns:
            bool: True unless the mount sits in the UNASSIGNED bucket
        """
        return self.area != RackArea.UNASSIGNED


    def get_occupied_slots(self) -> set[int]:
        """
        Returns every U this mount occupies, empty when it has no slot geometry

        A mount is anchored at its start_slot and extends DOWNWARD, so a 3U mount at slot 25 occupies
        25, 24 and 23. Only the main areas occupy slots; a side or unassigned mount occupies none.
        Delegates to the shared slot arithmetic so the model can never disagree with the validators

        Returns:
            set[int]: The occupied U numbers
        """
        return occupied_slots_of({
            RackMountKey.AREA.value: self.area,
            RackMountKey.START_SLOT.value: self.start_slot,
            RackMountKey.HEIGHT.value: self.height,
        })

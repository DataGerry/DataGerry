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
Limits and validation messages of the Rack View feature
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class RackLimits:
    """
    Numeric bounds of a Rack

    MIN_HEIGHT is the lowest U count a Rack may have. There is deliberately no maximum yet - a cap is
    an open product decision, and adding one later only ever rejects more, never less
    """
    MIN_HEIGHT: int = 1


class RackValidationError(BaseStrEnum):
    """
    Messages reported when a Rack CmdbObject fails validation

    Members with a `{...}` placeholder are filled via `format()`. The presence messages
    (MISSING_*) are reported by the object REST routes only - the bulk importer's own pipeline
    already rejects a missing required value before these rules run
    """
    MISSING_NAME = 'A Rack requires a Rackname!'
    BLANK_NAME = 'The Rackname of a Rack can not be blank!'
    MISSING_HEIGHT = 'A Rack requires a Height!'
    INVALID_HEIGHT = "The Height of a Rack must be a whole number, but was '{value}'!"
    NON_POSITIVE_HEIGHT = 'The Height of a Rack must be at least {minimum}, but was {value}!'


class RackOverviewKey(BaseStrEnum):
    """
    Keys of the rack overview document

    The wire format the rack view is drawn from, so these are a frontend contract. TYPE_LABEL, TYPE_ICON and
    TYPE_COLOR double as the keys of the batch-resolved type metadata, so the projection can read the lookup
    with the same names it writes out
    """
    RACK = 'rack'
    AREAS = 'areas'
    TOTAL_MOUNTS = 'total_mounts'

    PUBLIC_ID = 'public_id'
    DISPLAY_NAME = 'display_name'
    NAME = 'name'
    NUMBER = 'number'
    NOTES = 'notes'
    HEIGHT = 'height'

    MOUNT_ID = 'mount_id'
    OBJECT_ID = 'object_id'
    AREA = 'area'
    START_SLOT = 'start_slot'
    POSITION = 'position'
    SUMMARY_LINE = 'summary_line'
    TYPE_ID = 'type_id'
    TYPE_LABEL = 'type_label'
    TYPE_ICON = 'type_icon'
    # The colour the user picked for the type under Type Settings (CmdbType.ci_explorer_color), so a rack
    # draws each device in the same colour the CI-Explorer and the type chips use
    TYPE_COLOR = 'type_color'


class RackDisplayName:
    """
    Fallbacks for a Rack's display name

    `dg-rack-name` is required, so the first branch normally wins. The rest exist because required is a
    frontend marker and a Rack could predate the enforcement hook: rather than showing an empty label in
    the picker and the tree, the number and finally the public_id stand in
    """
    NUMBER_TEMPLATE: str = 'Rack #{number}'
    ID_TEMPLATE: str = 'Rack #{public_id}'


class RackMountError(BaseStrEnum):
    """
    Messages reported when a CmdbRackMount fails validation

    Members with a `{...}` placeholder are filled via `format()`. Every one of these is a business-rule
    rejection surfaced as an HTTP 400 by the mount routes
    """
    RACK_NOT_FOUND = 'No Rack with ID {rack_id} exists!'
    NOT_A_RACK = 'The CmdbObject with ID {rack_id} is not a Rack!'
    OBJECT_NOT_FOUND = 'No CmdbObject with ID {object_id} exists!'
    OBJECT_IS_THE_RACK = 'A Rack can not be mounted inside itself!'
    OBJECT_IS_A_RACK = 'A Rack can not be mounted inside another Rack!'
    OBJECT_ALREADY_MOUNTED = 'The CmdbObject with ID {object_id} is already mounted in a Rack - an ' \
                             'object can only be mounted in one Rack at a time!'
    INVALID_AREA = "'{area}' is not a valid Rack area. Allowed: {allowed}"
    MISSING_START_SLOT = 'A mount in the {area} area requires a start slot!'
    MISSING_HEIGHT = 'A mount in the {area} area requires a height!'
    INVALID_START_SLOT = 'The start slot must be a whole number of at least {minimum}, but was {value}!'
    INVALID_MOUNT_HEIGHT = 'The height of a mount must be a whole number of at least {minimum}, ' \
                           'but was {value}!'
    EXCEEDS_RACK_HEIGHT = 'Slot {start_slot} is above the Rack height of {rack_height}U!'
    BELOW_RACK_FLOOR = 'A mount of {height}U anchored at slot {start_slot} would reach down to slot ' \
                       '{bottom_slot}, below the bottom of the Rack!'
    SLOTS_OCCUPIED = 'Slots {slots} in the {area} area are already occupied by mount(s) {mount_ids}!'
    INVALID_POSITION = 'The position must be a whole number of at least {minimum}, but was {value}!'


ABORT_PREFIX: str = 'Rack validation failed'
MOUNT_ABORT_PREFIX: str = 'Rack mount validation failed'


class RackMountLimits:
    """
    Bounds of a single mount's geometry

    MIN_START_SLOT reflects U numbering starting at 1, MIN_HEIGHT that a mount occupies at least one U,
    and MIN_POSITION that the order index of an ordered area is zero-based
    """
    MIN_START_SLOT: int = 1
    MIN_HEIGHT: int = 1
    MIN_POSITION: int = 0

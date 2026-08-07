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
Rights, request keys and query parameters of the Rack REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class RackRight(BaseStrEnum):
    """
    ACL right identifiers guarding the Rack REST routes

    Every membership and placement write is guarded by EDIT: the requirement lists "add or remove an
    object" separately from "edit the values of the Rack", but both are the same right - there is no
    dedicated mount right. Note these guard the RACK, not the mounted object: a caller needs rack
    rights only, never object rights on what they are mounting
    """
    ADD = 'base.framework.rack.add'
    VIEW = 'base.framework.rack.view'
    EDIT = 'base.framework.rack.edit'
    DELETE = 'base.framework.rack.delete'


class RackMountRequestKey(BaseStrEnum):
    """
    Body keys a mount request may carry

    RACK_ID is deliberately absent: the rack comes from the URL, never from the body, so a request can
    not move a mount into a different rack by editing its payload.

    MOUNT_ID is accepted by the pre-validation route only, to say "I am validating a MOVE of this existing
    mount" - which excludes it from its own overlap and membership checks, exactly as the PATCH does
    """
    OBJECT_ID = 'object_id'
    AREA = 'area'
    START_SLOT = 'start_slot'
    HEIGHT = 'height'
    POSITION = 'position'
    MOUNT_ID = 'mount_id'


class RackMountParam(BaseStrEnum):
    """
    Query parameters of the mount read routes

    ONLY_UNMOUNTED belongs to the assignable-objects picker, which by default also offers the objects
    held by ANOTHER rack (mounting one moves it). It narrows the list back to the objects in no rack at
    all - which a ``?filter=`` can not express, because the rack a candidate sits in is resolved after
    the query and filtering on it in the frontend would break the paging
    """
    AREA = 'area'
    HEIGHT = 'height'
    ONLY_UNMOUNTED = 'only_unmounted'


class RackValidationResponseKey(BaseStrEnum):
    """
    Response-envelope keys of the mount pre-validation route

    Same shape as every /ipam/validate/* route: VALID is the boolean summary and ERRORS carries the reasons,
    so a frontend that already speaks to those routes meets a familiar answer. The per-error keys are named
    in ValidationErrorKey
    """
    VALID = 'valid'
    ERRORS = 'errors'


class RackConflictKey(BaseStrEnum):
    """
    Keys of the shrink pre-check response

    HEIGHT echoes the height that was tested, so a frontend holding several in-flight checks can tell
    which answer belongs to which candidate height
    """
    HEIGHT = 'height'
    CONFLICTS = 'conflicts'
    TOTAL = 'total'


class RackMountRouteError(BaseStrEnum):
    """
    Messages the mount routes report for a malformed or impossible request

    The geometry messages live in cmdb.framework.rack.rack_constants; these are the route-level ones
    """
    MISSING_OBJECT_ID = 'An object_id is required to mount an object into a Rack!'
    INVALID_OBJECT_ID = "'{value}' is not a valid object_id!"
    MOUNT_NOT_FOUND = 'No mount with ID {mount_id} exists in Rack {rack_id}!'
    UNKNOWN_AREA_FILTER = "'{area}' is not a valid Rack area to filter by. Allowed: {allowed}"
    MISSING_HEIGHT = "A 'height' to check against is required!"
    INVALID_HEIGHT = "'{value}' is not a valid Rack height to check against!"

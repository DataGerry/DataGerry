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
The object ACL on the Rack routes - the Rack itself, and the member a membership write moves

The rack rights (``RackRight``) say who may use the Rack view at all; the object ACL then says which Racks and
which members a caller may touch, the same way it does everywhere else an object is read or written:

* **every rack read** - the overview, the mounts, the height conflicts, the dry run, the picker, the mount of an
  object - asks READ on the Rack's type
* **every membership write** - mount (a cross-rack move included, for the rack it leaves as well), re-place,
  unmount - asks READ and UPDATE on the Rack's type, and READ and UPDATE on the member's: joining or leaving a
  rack moves the member in the location tree, which is a placement write (``location_helper.object_write_blocker``,
  the rule the ``/locations`` writes apply)

A refusal is a 403 naming the object, decided before anything is written - the same answer ``GET /objects/<id>``
gives. The dry run (``/mounts/validate``) reports the same reasons the write would refuse with
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.helpers import verify_access
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import object_write_blocker
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError

from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

#: The HTTP status of an ACL refusal - the one GET /objects/<id> answers
ACCESS_DENIED_STATUS: int = 403


def resolve_object_type(cmdb_object: dict[str, Any], objects_manager: ObjectsManager) -> CmdbType | None:
    """
    The CmdbType of a CmdbObject document

    Args:
        cmdb_object (dict[str, Any]): A CmdbObject document
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        CmdbType | None: Its type; None when the type no longer exists
    """
    return objects_manager.get_object_type(cmdb_object.get(CmdbObjectKey.TYPE_ID.value))


def rack_access_blocker(
        rack: dict[str, Any],
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None,
        write: bool) -> str | None:
    """
    Why the caller may not use this Rack - read it, or for a membership write also change it - or None

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to
        write (bool): Whether the route writes a membership (READ and UPDATE) or only reads (READ)

    Returns:
        str | None: The reason, or None when allowed. A rack whose type is missing is left to the type check
            that follows, which refuses it as no Rack
    """
    rack_id: Any = rack.get(CmdbObjectKey.PUBLIC_ID.value)
    rack_type: CmdbType | None = resolve_object_type(rack, objects_manager)

    if rack_type is None:
        return None

    if write:
        return object_write_blocker(
            rack_id, rack.get(CmdbObjectKey.TYPE_ID.value), rack_type, objects_manager, request_user,
            RackAccessError.RACK_READ_DENIED.value, RackAccessError.RACK_UPDATE_DENIED.value,
        )

    try:
        verify_access(rack_type, request_user, AccessControlPermission.READ)
    except AccessDeniedError:
        return RackAccessError.RACK_READ_DENIED.format(object_id=rack_id)

    return None


def authorize_rack_or_abort(
        rack: dict[str, Any],
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None,
        write: bool) -> None:
    """
    Refuses the route when the caller may not use this Rack

    Args:
        rack (dict[str, Any]): The Rack CmdbObject document
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to
        write (bool): Whether the route writes a membership

    Raises:
        HTTPException: 403 naming the Rack
    """
    blocker: str | None = rack_access_blocker(rack, objects_manager, request_user, write)

    if blocker:
        abort(ACCESS_DENIED_STATUS, blocker)


def member_access_blocker(
        member: dict[str, Any],
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None) -> str | None:
    """
    Why the caller may not move this object into, inside or out of a Rack - or None

    Args:
        member (dict[str, Any]): The member CmdbObject document
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to

    Returns:
        str | None: The reason (not readable, not changeable, type deactivated), or None when allowed. A member
            whose type is missing is left to the mount rules, which refuse it as having no location field
    """
    member_type: CmdbType | None = resolve_object_type(member, objects_manager)

    if member_type is None:
        return None

    return object_write_blocker(
        member.get(CmdbObjectKey.PUBLIC_ID.value), member.get(CmdbObjectKey.TYPE_ID.value), member_type,
        objects_manager, request_user,
    )


def authorize_member_or_abort(
        member_id: Any,
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None) -> None:
    """
    Refuses a membership write on an existing mount when the caller may not move its member

    Args:
        member_id (Any): The mount's object_id; None for an occupant, which names no object
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to

    Raises:
        HTTPException: 403 naming the member
    """
    if member_id is None:
        return

    member: dict[str, Any] | None = objects_manager.get_object(member_id)

    if not member:
        # The object is gone: there is nothing of it the write could move
        return

    blocker: str | None = member_access_blocker(member, objects_manager, request_user)

    if blocker:
        abort(ACCESS_DENIED_STATUS, blocker)


def authorize_move_source_or_abort(
        move_source: dict[str, Any] | None,
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None) -> None:
    """
    Refuses a cross-rack move when the caller may not change the Rack the object leaves

    Mounting an object another Rack holds deletes its mount there - a membership write on that Rack too

    Args:
        move_source (dict[str, Any] | None): The object's current mount in another Rack; None when it is in none
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to

    Raises:
        HTTPException: 403 naming the Rack the object would leave
    """
    if not move_source:
        return

    source_rack: dict[str, Any] | None = objects_manager.get_object(move_source.get(RackMountKey.RACK_ID.value))

    if source_rack:
        authorize_rack_or_abort(source_rack, objects_manager, request_user, write=True)


def authorize_object_read_or_abort(
        object_id: int,
        objects_manager: ObjectsManager,
        request_user: CmdbUser | None) -> None:
    """
    Refuses a read about an object - which rack it is mounted in - when the caller may not read the object

    Args:
        object_id (int): public_id of the CmdbObject
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser | None): The caller; None is an internal caller, which no ACL applies to

    Raises:
        HTTPException: 403 when the object exists and its type does not grant READ
    """
    cmdb_object: dict[str, Any] | None = objects_manager.get_object(object_id)
    object_type: CmdbType | None = resolve_object_type(cmdb_object, objects_manager) if cmdb_object else None

    if object_type is None:
        return

    try:
        verify_access(object_type, request_user, AccessControlPermission.READ)
    except AccessDeniedError:
        abort(ACCESS_DENIED_STATUS, RackAccessError.OBJECT_READ_DENIED.format(object_id=object_id))

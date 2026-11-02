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
The reads of an object update: the target with its type and read check, and the document after the write

An update reads its target once - raw, because that very document is the write ledger's snapshot - and takes the
target's type from the request's ``ObjectWriteContext.type_cache``, so the objects of one type cost one type read
however many of them a bulk update names. The read permission is judged on that cached type. After the write the
stored document is read once more, raw: the consequences change it further, and its read permission and type were
settled before the write
"""
import copy
from dataclasses import dataclass
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.helpers import verify_access
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.models.cmdb_object import CmdbObjectInitFromDataError

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
# -------------------------------------------------------------------------------------------------------------------- #

@dataclass(frozen=True)
class UpdateTarget:
    """
    An update's target as read once before the write

    Attributes:
        stored_document (dict[str, Any]): The raw stored document - the write ledger's snapshot, never changed
        current_object (CmdbObject): The stored object, built from a copy of the document
        current_type (CmdbType): The object's type, from the request's type cache
    """
    stored_document: dict[str, Any]
    current_object: CmdbObject
    current_type: CmdbType


def resolve_object_type(
        objects_manager: ObjectsManager,
        type_id: int,
        type_cache: dict[int, CmdbType] | None = None,
    ) -> CmdbType:
    """
    Resolves a CmdbObject's CmdbType, reusing an already resolved one when a cache is passed

    Every type read costs a query plus building the model, and a bulk update usually targets objects of
    the SAME type - so a caller that iterates hands in a cache and pays for each distinct type once
    instead of once per object. The cache is filled as types are resolved

    Args:
        objects_manager (ObjectsManager): Manager used to read the CmdbType
        type_id (int): public_id of the CmdbType to resolve
        type_cache (dict[int, CmdbType] | None): Types already resolved by this caller, extended in
                                                 place. Defaults to None (always read)

    Raises:
        HTTPException: 500 when the type does not exist

    Returns:
        CmdbType: The resolved CmdbType
    """
    if type_cache is not None and type_id in type_cache:
        return type_cache[type_id]

    object_type: CmdbType | None = objects_manager.get_object_type(type_id)

    if not object_type:
        abort(500, "Type of Object not found in database!")

    if type_cache is not None:
        type_cache[type_id] = object_type

    return object_type


def read_stored_object(objects_manager: ObjectsManager, obj_id: int) -> dict[str, Any] | None:
    """
    Reads one stored CmdbObject document as it is, the database's failure as the manager's own

    Args:
        objects_manager (ObjectsManager): Manager used to read the object
        obj_id (int): public_id of the CmdbObject

    Raises:
        ObjectsManagerGetError: When the read fails

    Returns:
        dict[str, Any] | None: The raw stored document, None when there is none
    """
    try:
        return objects_manager.get_one(obj_id)
    except BaseManagerGetError as err:
        raise ObjectsManagerGetError(err) from err


def read_update_target(obj_id: int, context: ObjectWriteContext) -> UpdateTarget:
    """
    Reads an update's target once: the raw document, the object built from a copy of it, and its cached type

    The caller's READ on the type is checked here, with the type the context already holds - the read check
    ``ObjectsManager.get_object`` would make, without its own type read. The raw document is left untouched: it is
    what the write ledger records to put the object back

    Args:
        obj_id (int): public_id of the CmdbObject to update
        context (ObjectWriteContext): The caller, the managers and the type cache

    Raises:
        HTTPException: 404 when the object does not exist; 500 when its type does not
        AccessDeniedError: When the caller's group may not READ the object's type
        ObjectsManagerGetError: When the object cannot be read or built

    Returns:
        UpdateTarget: The stored document, the stored object, its type
    """
    stored_document: dict[str, Any] | None = read_stored_object(context.objects_manager, obj_id)

    if not stored_document:
        abort(404, f"Object with ID:{obj_id} not found!")

    try:
        current_object: CmdbObject = CmdbObject.from_data(copy.deepcopy(stored_document))
    except CmdbObjectInitFromDataError as err:
        raise ObjectsManagerGetError(err) from err

    current_type: CmdbType = resolve_object_type(
        context.objects_manager, current_object.get_type_id(), context.type_cache,
    )
    verify_access(current_type, context.request_user, AccessControlPermission.READ)

    return UpdateTarget(stored_document, current_object, current_type)

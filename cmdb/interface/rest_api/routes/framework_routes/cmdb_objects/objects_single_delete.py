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
The delete of one CmdbObject with every guard and clean-up - the single delete route's body, shared with the person
and person-group routes, which delete their objects the same way
"""
from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject, ObjectWriteVerb
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.framework.person_selector.selector_delete import scrub_person_selectors
from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_person_selector_helper import (
    clear_deleted_from_isms,
    selectable_target_ids,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import delete_one_cascade
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_guard import guard_object_delete
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_update_read import resolve_object_type
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    handle_delete_object_location,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_cleanup import run_delete_cleanup_step
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import DeleteCleanupStep
# -------------------------------------------------------------------------------------------------------------------- #

def delete_object_with_cleanup(public_id: int, request_user: CmdbUser) -> CmdbObject:
    """
    Deletes one CmdbObject: authorizes, guards, deletes, then runs every clean-up step

    Authorizes first: the object's type must exist and be active and its ACL must grant the caller DELETE
    (`ObjectsManager.guard_writable_type`) before anything is touched, because the steps that follow - the location
    node, the rack and port state, the risk assessments - are not undone when a later check refuses. Then the delete
    guards (`guard_object_delete`), the location, the delete itself, and the best-effort clean-up: the references of
    other objects, the person selections, the ISMS references to a person or group, and `delete_one_cascade`

    Args:
        public_id (int): public_id of the CmdbObject to delete
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 404 when the object does not exist; 403 when its type is deactivated or its ACL denies DELETE;
            400 when a delete guard refuses; 500 when the object's type is missing
        ObjectsManagerGetError: When a read fails
        ObjectsManagerDeleteError: When the delete fails
        AccessDeniedError: When the delete itself is refused by the ACL

    Returns:
        CmdbObject: The deleted object, as it was
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    to_delete_object: CmdbObject | None = objects_manager.get_object(public_id, as_dict=False)

    if not to_delete_object:
        abort(404, f"Object with ID:{public_id} not found!")

    # The one read of the type: every check and clean-up below is handed it (500 when the type is gone)
    to_delete_object_type: CmdbType = resolve_object_type(objects_manager, to_delete_object.get_type_id())

    # Authorized before any side effect: every step below changes data a later refusal would not restore
    objects_manager.guard_writable_type(
        to_delete_object.get_type_id(), request_user, AccessControlPermission.DELETE,
        ObjectsManagerDeleteError, ObjectWriteVerb.REMOVED.value, to_delete_object_type,
    )

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    deleted_document = CmdbObject.to_json(to_delete_object)

    # Deleting an IPAM special-type object needs a valid IPAM license + passes the delete guards
    guard_object_delete(objects_manager, types_manager, request_user, deleted_document, to_delete_object_type)

    # An object can not be deleted if it has a location AND the location is a parent for other locations
    handle_delete_object_location(request_user, public_id)

    # Delete the Object (reusing the already-resolved type to skip a per-object type lookup)
    objects_manager.delete_with_follow_up(
        public_id, request_user, AccessControlPermission.DELETE, object_type=to_delete_object_type
    )

    # Remove all references to this object from other CmdbObjects - best-effort like the cascade: the object is gone
    run_delete_cleanup_step(DeleteCleanupStep.REFERENCES, [public_id],
                            lambda: objects_manager.delete_all_object_references(public_id))

    # Only a person or a group can be selected
    if selectable_target_ids(types_manager, [deleted_document], {to_delete_object_type.public_id: to_delete_object_type}):
        run_delete_cleanup_step(DeleteCleanupStep.PERSON_SELECTORS, [public_id],
                                lambda: scrub_person_selectors(objects_manager, types_manager, [public_id]))

    # A deleted person or group leaves the ISMS documents naming it (the risk owner was refused up front)
    run_delete_cleanup_step(DeleteCleanupStep.ISMS_PERSON_REFERENCES, [public_id],
                            lambda: clear_deleted_from_isms(objects_manager, [deleted_document]))

    # Cascade the deletion to relevant collections
    delete_one_cascade(request_user, to_delete_object, objects_manager, LogAction.DELETE, to_delete_object_type)

    return to_delete_object

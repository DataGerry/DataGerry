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
Implementation of all API routes for handling CmdbRackMounts

These routes are the only way a mount is written. Four invariants hold across them:

1. **The rack comes from the URL.** A body can not carry a rack_id, so no request can move a mount into
   another rack by editing its payload.
2. **The identity and the audit fields are server-owned.** A payload public_id is ignored, and
   `author_id` / `creation_time` / `last_edit_time` are stamped from the request.
3. **An object belongs to one rack.** Enforced by a unique index on `object_id`; the routes pre-check it
   so the caller gets a readable 400 rather than a duplicate-key error.
4. **Membership and placement are separate.** A `POST` with no area assigns the object to the rack
   without placing it (the UNASSIGNED bucket); a `PATCH` places, moves or unplaces it. `DELETE` is the
   stronger verb - it removes the object from the rack entirely, but never touches the object itself.

A Rack itself is an ordinary CmdbObject, so it is created and edited through the /objects routes.
Location mirroring and the CI-Explorer are deliberately NOT wired up here yet: the mount row is the
authority and the location tree is a projection of it, so the authority is built first
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.rack_model.rack_mount_constants import RackMountKey

from cmdb.utils.validation_error import build_error

from cmdb.errors.manager.rack_mounts_manager import (
    RackMountsManagerInsertError,
    RackMountsManagerGetError,
    RackMountsManagerUpdateError,
    RackMountsManagerDeleteError,
)

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
    DefaultResponse,
)
from cmdb.framework.rack.height_change import get_height_conflicts
from cmdb.framework.rack.overview import build_mount_row, build_rack_overview

from cmdb.interface.rest_api.routes.rack_routes.rack_location_helper import (
    handle_mount_created,
    handle_mount_removed,
)

from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import (
    RackRight,
    RackConflictKey,
    RackMountParam,
    RackMountRequestKey,
    RackValidationResponseKey,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import (
    apply_mount_changes,
    assign_position_if_needed,
    build_mount_candidate,
    collect_mount_blockers,
    get_area_filter_or_abort,
    get_mount_of_rack_or_abort,
    get_rack_display_name,
    get_rack_height,
    get_rack_or_abort,
    get_requested_height_or_abort,
    refuse_second_membership,
    resolve_mounted_object_meta,
    validate_member_object_or_abort,
    validate_placement_or_abort,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

rack_mounts_blueprint = APIBlueprint('rack_mounts', __name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - CREATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@rack_mounts_blueprint.route('/<int:rack_id>/mounts/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.EDIT.value)
def insert_rack_mount(rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to mount a CmdbObject into a Rack

    With no area the object is assigned to the rack without being placed in it (the UNASSIGNED bucket);
    with a main area it is placed, which requires a start slot and a height and is refused when the
    slots are taken or the mount would stick out of the rack

    Args:
        rack_id (int): public_id of the Rack the object is mounted into
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the object may not be mounted or the placement is invalid, 404 when the
                       Rack does not exist, 500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbRackMount and its public_id
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        rack: dict[str, Any] = get_rack_or_abort(objects_manager, types_manager, rack_id)

        object_id: int = validate_member_object_or_abort(
            objects_manager, types_manager, rack_id, payload.get(RackMountRequestKey.OBJECT_ID.value),
        )
        refuse_second_membership(rack_mounts_manager, object_id)

        candidate: dict[str, Any] = build_mount_candidate(rack_id, object_id, payload)

        validate_placement_or_abort(rack_mounts_manager, candidate, get_rack_height(rack))
        assign_position_if_needed(rack_mounts_manager, candidate)

        candidate[RackMountKey.AUTHOR_ID.value] = request_user.get_public_id()
        candidate[RackMountKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        candidate[RackMountKey.LAST_EDIT_TIME.value] = None

        mount_id: int = rack_mounts_manager.insert_item(candidate)

        created: dict[str, Any] | None = rack_mounts_manager.get_item(mount_id, as_dict=True)

        if not created:
            abort(404, "Could not retrieve the created Rack mount from the database!")

        # The tree follows membership, so the member is placed under the rack as soon as it joins - whether
        # or not it was given a slot. A no-op while the rack itself has no location
        handle_mount_created(
            rack_id, object_id, request_user, objects_manager,
            ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user),
        )

        return InsertSingleResponse(created, mount_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerInsertError as err:
        LOGGER.error("[insert_rack_mount] %s", err, exc_info=True)
        abort(400, "Could not mount the object into the Rack!")
    except RackMountsManagerGetError as err:
        LOGGER.error("[insert_rack_mount] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Rack mount from the database!")
    except Exception as err:
        LOGGER.error("[insert_rack_mount] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while mounting the object into the Rack!")

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CRUD - READ                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@rack_mounts_blueprint.route('/<int:rack_id>/mounts/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def get_rack_mounts(rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to list the CmdbRackMounts of a Rack

    Returns the raw mounts, optionally limited to one area with `?area=`. This is the membership list,
    not the rack view: resolving each mounted object and computing the free slot ranges is the job of
    the overview route

    Args:
        rack_id (int): public_id of the Rack
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 on an unknown area filter, 404 when the Rack does not exist, 500 on an
                       unexpected error

    Returns:
        DefaultResponse: The Rack's mounts
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        get_rack_or_abort(objects_manager, types_manager, rack_id)

        area: str | None = get_area_filter_or_abort(request.args.get(RackMountParam.AREA.value))

        return DefaultResponse(rack_mounts_manager.get_mounts_of_rack(rack_id, area)).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerGetError as err:
        LOGGER.error("[get_rack_mounts] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the mounts of the Rack!")
    except Exception as err:
        LOGGER.error("[get_rack_mounts] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Rack mounts!")



@rack_mounts_blueprint.route('/<int:rack_id>/mounts/validate', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def validate_rack_mount(rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a mount candidate without writing anything

    The dry run behind a drag-and-drop: it answers "would this be accepted, and if not why" for one candidate
    placement. Writes nothing, so it is safe to call while the user is still dragging

    It runs the same checks the real write runs, through the same blocker cores, so it can never accept a
    placement the write would refuse. `errors` names the reason - including which mounts hold the contested
    slots - so the UI can say why rather than just no

    Body: `object_id` (required), plus the optional `area`, `start_slot`, `height`, `position` of the intended
    placement, and `mount_id` when validating a MOVE of an existing mount (which excludes that mount from its
    own overlap and membership checks). With no area the candidate is an assignment to the rack without a
    placement, which is what the write would do too

    Args:
        rack_id (int): public_id of the Rack the object would be mounted into
        request_user (CmdbUser): CmdbUser requesting this check

    Raises:
        HTTPException: 400 when the object is not a Rack, 404 when the Rack does not exist, 500 on an
                       unexpected error

    Returns:
        DefaultResponse: `{'valid': bool, 'errors': [{'message': str}, ...]}`
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        rack: dict[str, Any] = get_rack_or_abort(objects_manager, types_manager, rack_id)

        blockers: list[str] = collect_mount_blockers(
            objects_manager, types_manager, rack_mounts_manager, rack, rack_id, payload,
        )

        return DefaultResponse({
            RackValidationResponseKey.VALID.value: not blockers,
            RackValidationResponseKey.ERRORS.value: [build_error(message) for message in blockers],
        }).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerGetError as err:
        LOGGER.error("[validate_rack_mount] %s", err, exc_info=True)
        abort(400, "Failed to check the Rack mount candidate!")
    except Exception as err:
        LOGGER.error("[validate_rack_mount] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while checking the Rack mount candidate!")


@rack_mounts_blueprint.route('/<int:rack_id>/overview', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def get_rack_overview(rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve everything needed to draw one Rack

    One document: the rack's own fields, its mounts grouped per area and resolved to each object's
    summary line and type metadata, the free slot ranges per placement target, and the member count.
    Three bulk reads regardless of how full the rack is, so opening a rack costs the same whether it
    holds one object or forty

    The free ranges are computed from the same conflict map the mount write enforces, so the overview can
    not offer a slot the write would then refuse

    Args:
        rack_id (int): public_id of the Rack
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the object is not a Rack or a read fails, 404 when the Rack does not
                       exist, 500 on an unexpected error

    Returns:
        DefaultResponse: The rack overview document
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        rack: dict[str, Any] = get_rack_or_abort(objects_manager, types_manager, rack_id)
        mounts: list[dict[str, Any]] = rack_mounts_manager.get_mounts_of_rack(rack_id)

        summary_lines, type_meta, object_types = resolve_mounted_object_meta(
            objects_manager, types_manager, mounts,
        )

        overview: dict[str, Any] = build_rack_overview(
            rack,
            get_rack_height(rack),
            get_rack_display_name(rack),
            mounts,
            summary_lines,
            type_meta,
            object_types,
        )

        return DefaultResponse(overview).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerGetError as err:
        LOGGER.error("[get_rack_overview] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the mounts of the Rack!")
    except Exception as err:
        LOGGER.error("[get_rack_overview] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while building the Rack overview!")


@rack_mounts_blueprint.route('/<int:rack_id>/height_conflicts', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def get_rack_height_conflicts(rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to check which mounts a height reduction would displace

    The pre-check behind "these 3 objects no longer fit": a frontend calls it with the candidate height
    before saving so the user can confirm. Writes nothing - lowering the height is what actually unplaces
    the reported mounts, and it does so whether or not this route was called, so an API client that skips
    it still ends up consistent

    Args:
        rack_id (int): public_id of the Rack
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the height is missing or unusable or the object is not a Rack, 404 when
                       the Rack does not exist, 500 on an unexpected error

    Returns:
        DefaultResponse: The tested height and the mounts that would be unplaced
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        get_rack_or_abort(objects_manager, types_manager, rack_id)

        height: int = get_requested_height_or_abort(request.args.get(RackMountParam.HEIGHT.value))

        conflicts: list[dict[str, Any]] = get_height_conflicts(rack_mounts_manager, rack_id, height)

        summary_lines, type_meta, object_types = resolve_mounted_object_meta(
            objects_manager, types_manager, conflicts,
        )

        return DefaultResponse({
            RackConflictKey.HEIGHT.value: height,
            RackConflictKey.CONFLICTS.value: [
                build_mount_row(mount, summary_lines, type_meta, object_types) for mount in conflicts
            ],
            RackConflictKey.TOTAL.value: len(conflicts),
        }).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerGetError as err:
        LOGGER.error("[get_rack_height_conflicts] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the mounts of the Rack!")
    except Exception as err:
        LOGGER.error("[get_rack_height_conflicts] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while checking the Rack height!")


@rack_mounts_blueprint.route('/mounts/object/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def get_rack_mount_of_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to answer "where is this CmdbObject mounted?"

    An object belongs to at most one Rack, so this is a single mount or nothing. Backs the object view,
    which has no other way to know the object sits in a Rack - the mount lives in its own collection,
    not on the object

    Args:
        object_id (int): public_id of the CmdbObject
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the lookup fails, 500 on an unexpected error

    Returns:
        DefaultResponse: The CmdbRackMount holding the object, or None when it is not mounted
    """
    try:
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        return DefaultResponse(rack_mounts_manager.get_mount_of_object(object_id)).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerGetError as err:
        LOGGER.error("[get_rack_mount_of_object] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Rack mount of the object!")
    except Exception as err:
        LOGGER.error("[get_rack_mount_of_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Rack mount of the object!")

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@rack_mounts_blueprint.route('/<int:rack_id>/mounts/<int:mount_id>', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.EDIT.value)
def update_rack_mount(rack_id: int, mount_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route to place, move, resize, reorder or unplace a mounted CmdbObject

    Only the keys the body carries are applied, so a request naming just an area moves the mount without
    touching its geometry. Setting the area to UNASSIGNED unplaces the object: its slots are freed and
    it stays a member of the Rack, with its height kept as a hint for re-placing it. The mount being
    changed is excluded from its own overlap check, so re-slotting does not collide with where it is

    Args:
        rack_id (int): public_id of the Rack owning the mount
        mount_id (int): public_id of the CmdbRackMount to change
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the requested placement is invalid, 404 when the Rack or the mount does
                       not exist, 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The updated CmdbRackMount
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        rack: dict[str, Any] = get_rack_or_abort(objects_manager, types_manager, rack_id)
        stored: dict[str, Any] = get_mount_of_rack_or_abort(rack_mounts_manager, rack_id, mount_id)

        candidate: dict[str, Any] = apply_mount_changes(stored, payload)

        validate_placement_or_abort(
            rack_mounts_manager, candidate, get_rack_height(rack), exclude_mount_id=mount_id,
        )
        assign_position_if_needed(rack_mounts_manager, candidate)

        # The identity, the membership and the authorship are never taken from the body
        candidate[RackMountKey.PUBLIC_ID.value] = mount_id
        candidate[RackMountKey.RACK_ID.value] = rack_id
        candidate[RackMountKey.OBJECT_ID.value] = stored[RackMountKey.OBJECT_ID.value]
        candidate[RackMountKey.AUTHOR_ID.value] = stored.get(RackMountKey.AUTHOR_ID.value)
        candidate[RackMountKey.CREATION_TIME.value] = stored.get(RackMountKey.CREATION_TIME.value)
        candidate[RackMountKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        rack_mounts_manager.update_item(mount_id, candidate)

        updated: dict[str, Any] | None = rack_mounts_manager.get_item(mount_id, as_dict=True)

        if not updated:
            abort(404, "Could not retrieve the updated Rack mount from the database!")

        return UpdateSingleResponse(updated).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerUpdateError as err:
        LOGGER.error("[update_rack_mount] %s", err, exc_info=True)
        abort(400, "Could not update the Rack mount!")
    except RackMountsManagerGetError as err:
        LOGGER.error("[update_rack_mount] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the updated Rack mount from the database!")
    except Exception as err:
        LOGGER.error("[update_rack_mount] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating the Rack mount!")

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - DELETE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@rack_mounts_blueprint.route('/<int:rack_id>/mounts/<int:mount_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_mounts_blueprint.protect(auth=True, right=RackRight.EDIT.value)
def delete_rack_mount(rack_id: int, mount_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to remove a CmdbObject from a Rack

    Removes the MEMBERSHIP only - the CmdbObject itself is never touched and survives untouched. This is
    the stronger of the two removal verbs: to keep the object in the Rack but free its slots, PATCH its
    area to UNASSIGNED instead

    Note this is guarded by the Rack's edit right, not delete: deleting a Rack means deleting the Rack
    CmdbObject, while un-mounting is a change to the Rack's layout

    Args:
        rack_id (int): public_id of the Rack owning the mount
        mount_id (int): public_id of the CmdbRackMount to remove
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 404 when the Rack or the mount does not exist, 400 when the delete fails, 500 on
                       an unexpected error

    Returns:
        DeleteSingleResponse: The removed CmdbRackMount
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        get_rack_or_abort(objects_manager, types_manager, rack_id)
        mount: dict[str, Any] = get_mount_of_rack_or_abort(rack_mounts_manager, rack_id, mount_id)

        if not rack_mounts_manager.delete_item(mount_id):
            abort(400, "Could not remove the object from the Rack!")

        # Leaving the rack means leaving the tree - unlike merely being unplaced, which keeps the member
        # under the rack because the tree follows membership
        handle_mount_removed(
            mount[RackMountKey.OBJECT_ID.value],
            request_user,
            objects_manager,
            ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user),
        )

        return DeleteSingleResponse(mount).make_response()
    except HTTPException as http_err:
        raise http_err
    except RackMountsManagerDeleteError as err:
        LOGGER.error("[delete_rack_mount] %s", err, exc_info=True)
        abort(400, "Could not remove the object from the Rack!")
    except Exception as err:
        LOGGER.error("[delete_rack_mount] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while removing the object from the Rack!")

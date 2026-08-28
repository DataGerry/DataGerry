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
REST API routes for CmdbType CRUD

Blueprint ``types_blueprint`` is mounted at ``/rest/types`` (see ``init_rest_api.py``). Endpoints:

    POST   /                                       insert_cmdb_type
    GET    /                                       get_cmdb_types
    GET    /overview                                get_cmdb_types_overview
    GET    /<public_id>                             get_cmdb_type
    GET    /count_objects/<public_id>               count_objects_of_cmdb_type
    GET    /location_field_usage/<public_id>        get_location_field_usage_of_cmdb_type
    GET    /selectable_as_parent_usage/<public_id>  get_selectable_as_parent_usage_of_cmdb_type
    PUT    /<public_id>                             update_cmdb_type
    PATCH  /<public_id>                             update_cmdb_type
    DELETE /<public_id>                             delete_cmdb_type

All routes require authentication (JWT or ``x-api-key`` in cloud mode), ApiLevel.ADMIN and the
per-route ``base.framework.type.*`` right (see ``TypeRight``). Domain logic lives in
``TypesManager`` and ``types_helper``; manager-layer errors map to HTTP 400 (business-rule /
lookup failures) or HTTP 500 (unexpected), following the codebase convention - 409 is not used.
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort, request
from pymongo.results import UpdateResult
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import TypesManager, ObjectsManager, UsersManager, SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.object_model import CmdbObjectKey
from cmdb.framework.results import IterationResult
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.routes_helper import fetch_only_active_objects
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    verify_type_is_unique,
    prepare_builder_parameters,
    verify_type_deletable,
    type_deletion_followup,
    special_type_is_unchanged,
    build_location_usage_payload,
    get_type_or_404,
    get_type_instance_or_404,
    guard_location_field_removal,
    guard_selectable_as_parent_change,
    compute_removed_global_templates,
    apply_type_update_side_effects,
    build_types_overview_items,
    enforce_special_type_license,
    enforce_rack_selectable_as_parent,
)
from cmdb.framework.ipam.special_type_wiring import handle_special_types
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import TypeIterationParameters
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    DefaultResponse,
)

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerInsertError,
    TypesManagerDeleteError,
    TypesManagerIterationError,
    TypesManagerUpdateError,
    TypesManagerUpdateMDSError,
)
from cmdb.errors.manager.locations_manager import LocationsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

types_blueprint = APIBlueprint('types', __name__)

# What each pre-check route is determining, interpolated into the shared failure messages
LOCATION_FIELD_USAGE_SUBJECT: str = 'location-field usage'
SELECTABLE_AS_PARENT_USAGE_SUBJECT: str = 'selectable-as-parent usage'

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@types_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.ADD.value)
@types_blueprint.validate(CmdbType.SCHEMA)
def insert_cmdb_type(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbType into the database

    Requires the ``base.framework.type.add`` right and ApiLevel.ADMIN. The author and the creation
    time are stamped server-side, a duplicate type name is refused, and for a SpecialType the IPAM
    license is checked and the SpecialType wiring (ref_types cross-wiring, predefined sections) runs
    before the response is built

    Note:
        A payload ``public_id`` is currently honoured - the database only generates one when the key
        is absent - so a client can choose the new Type's id (discussion backlog #186)

    Args:
        data (CmdbType.SCHEMA): Data of the CmdbType which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license; 400 when the payload
            carries no name, the name is already taken or the insert fails; 404 when the created
            Type cannot be read back; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbType and its public_id
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        # Creating an IPAM special type (Supernet/Subnet/VLAN) requires a valid IPAM license
        enforce_special_type_license(request_user, data.get(TypeSchemaKey.SPECIAL_TYPE))

        # A Rack must stay selectable as a parent Location or nothing could be placed in it
        enforce_rack_selectable_as_parent(data.get(TypeSchemaKey.SPECIAL_TYPE), data)

        data.setdefault(TypeSchemaKey.CREATION_TIME, datetime.now(timezone.utc))
        data[TypeSchemaKey.AUTHOR_ID] = request_user.public_id

        verify_type_is_unique(
            types_manager,
            data.get(TypeSchemaKey.NAME),
            data.get(TypeSchemaKey.PUBLIC_ID),
            data.get(TypeSchemaKey.SPECIAL_TYPE),
        )

        result_id: int = types_manager.insert_type(data)
        created_type: dict[str, Any] | None = types_manager.get_type(result_id)

        if not created_type:
            abort(404, "Could not retrieve the created Type from the database!")

        special_type: str | None = created_type.get(TypeSchemaKey.SPECIAL_TYPE)

        if special_type:
            section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
                ManagerType.SECTION_TEMPLATES,
                request_user,
            )
            handle_special_types(types_manager, special_type, section_templates_manager, result_id)

            # Re-fetch so cross-wired 'ref_types' written by handle_special_types are in the response
            created_type = types_manager.get_type(result_id) or created_type

        return InsertSingleResponse(created_type, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to retrieve the created Type from the database!")
    except TypesManagerInsertError as err:
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to insert the new Type into the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new Type!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@types_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@types_blueprint.parse_parameters(TypeIterationParameters)
def get_cmdb_types(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbTypes

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN

    Args:
        params (TypeIterationParameters): Filter, sort, pagination and the 'active' flag for the
            requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the iteration fails; 500 on an unexpected error

    Returns:
        GetMultiResponse: All the CmdbTypes matching the TypeIterationParameters
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        builder_params: BuilderParameters = prepare_builder_parameters(params)

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(builder_params)
        types: list[dict[str, Any]] = [CmdbType.to_json(type) for type in iteration_result.results]

        api_response = GetMultiResponse(
            types,
            total=iteration_result.total,
            params=params,
            url=request.url,
            body=request.method == 'HEAD'
        )

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerIterationError as err:
        LOGGER.error("[get_cmdb_types] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Types!")


@types_blueprint.route('/overview', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@types_blueprint.parse_parameters(TypeIterationParameters)
def get_cmdb_types_overview(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the types overview listing

    Returns the filtered CmdbTypes each bundled with its resolved author/editor display block, so
    the overview renders author/editor names without a per-type user lookup (they are resolved in a
    single bulk query). Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN

    Args:
        params (TypeIterationParameters): Filter/pagination for the requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the iteration fails; 500 on an unexpected error

    Returns:
        GetMultiResponse: The matching CmdbTypes, each as a {type_data, user_data} item
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        builder_params: BuilderParameters = prepare_builder_parameters(params)

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(builder_params)
        types: list[dict[str, Any]] = [CmdbType.to_json(type) for type in iteration_result.results]

        # Get all users which interacted with the filtered types
        user_ids = {
            uid
            for t in types
            for uid in (t.get(TypeSchemaKey.AUTHOR_ID), t.get(TypeSchemaKey.EDITOR_ID))
            if uid is not None
        }

        user_lookup: dict[int, CmdbUser] = users_manager.get_user_lookup(user_ids)

        # Build the per-type {type_data, user_data} items
        response_items: list[dict[str, Any]] = build_types_overview_items(types, user_lookup)

        api_response = GetMultiResponse(
            response_items,
            total=iteration_result.total,
            params=params,
            url=request.url,
            body=request.method == 'HEAD'
        )

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerIterationError as err:
        LOGGER.error("[get_cmdb_types_overview] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_types_overview] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Types overview!")


@types_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def get_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbType

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 400 when the read fails;
            500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        requested_type: dict[str, Any] = get_type_or_404(types_manager, public_id)

        return GetSingleResponse(requested_type, body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[get_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Type with ID:{public_id}!")


@types_blueprint.route('/count_objects/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def count_objects_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Counts the number of CmdbObjects in the database with the given public_id as the type_id

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. Inactive CmdbObjects are
    excluded when the request asks for active objects only (see fetch_only_active_objects). A
    missing Type is not an error - it simply has no objects, so the count is 0

    Note:
        The count covers every CmdbObject of the Type regardless of the caller's object ACL, so it
        can exceed what the same user is allowed to see (discussion backlog #189)

    Args:
        public_id (int): The public_id of the CmdbType to count CmdbObjects for
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the count fails; 500 on an unexpected error

    Returns:
        DefaultResponse: An API response containing the count of CmdbObjects for the given type_id
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        count_query: dict[str, Any] = {CmdbObjectKey.TYPE_ID: public_id}

        if fetch_only_active_objects():
            count_query[CmdbObjectKey.ACTIVE] = True

        objects_count: int = objects_manager.count_documents(count_query)

        return DefaultResponse(objects_count).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[count_objects_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[count_objects_of_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while counting Objects for Type with ID: {public_id}!")


def build_type_usage_response(public_id: int, request_user: CmdbUser, route_name: str, subject: str) -> Response:
    """
    Answers a "is this Type's location placement still in use" pre-check route

    Both pre-check routes below ask the same underlying question - are any CmdbObjects of this Type
    placed in the location tree - and answer it with the same payload, so they share this body and
    only pass their own name (for the logs) and the subject of their failure messages

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data
        route_name (str): Name of the calling route, used as the log prefix
        subject (str): What the caller was determining, used in the failure messages

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 400 when the Type or its
            CmdbObjects could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, count: int, object_public_ids: list[int] }
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        target_type: CmdbType = get_type_instance_or_404(types_manager, public_id)

        return DefaultResponse(build_location_usage_payload(request_user, target_type)).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[%s] ObjectsManagerGetError: %s", route_name, err, exc_info=True)
        abort(400, f"Failed to determine {subject} for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[%s] TypesManagerGetError: %s", route_name, err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[%s] Exception: %s. Type: %s", route_name, err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while determining {subject} for Type with ID: {public_id}!")


@types_blueprint.route('/location_field_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def get_location_field_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns the public_ids of CmdbObjects that have a value (integer > 0) in the
    location-typed field of the given CmdbType

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. The frontend
    (``type.service.ts``) calls this to decide whether the location field may be removed from the
    CmdbType; the same check is enforced server-side on update by guard_location_field_removal

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 400 when the Type or its
            CmdbObjects could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, count: int, object_public_ids: list[int] }
    """
    return build_type_usage_response(
        public_id, request_user, 'get_location_field_usage_of_cmdb_type', LOCATION_FIELD_USAGE_SUBJECT,
    )


@types_blueprint.route('/selectable_as_parent_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def get_selectable_as_parent_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns whether the given CmdbType still has placed CmdbObjects, blocking a selectable-as-parent
    change to false

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. A CmdbType may only stop
    being selectable as a parent once no CmdbObject of it is placed in the location tree (holds a
    location value > 0); the same check is enforced server-side on update by
    guard_selectable_as_parent_change

    Note:
        This route has **no frontend caller** - the type builder toggles 'selectable_as_parent'
        locally and only learns of the block from the 400 the update route returns. Whether the
        frontend should pre-check here or the route should be retired is a pending decision
        (discussion backlog #188)

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 400 when the Type or its
            CmdbObjects could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, count: int, object_public_ids: list[int] }
    """
    return build_type_usage_response(
        public_id, request_user, 'get_selectable_as_parent_usage_of_cmdb_type', SELECTABLE_AS_PARENT_USAGE_SUBJECT,
    )

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.EDIT.value)
@types_blueprint.validate(CmdbType.SCHEMA)
def update_cmdb_type(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbType

    Requires the ``base.framework.type.edit`` right and ApiLevel.ADMIN. The write is always a full
    document (there is no partial update): the editor and the edit time are stamped server-side, the
    identity is pinned to the URL public_id, and three changes are refused outright - changing the
    SpecialType, removing the location field while CmdbObjects still hold a location value, and
    turning 'selectable_as_parent' off while CmdbObjects of the Type are placed in the tree

    Once the document is written, the side effects run (dropped global templates removed,
    SpecialType ref_types re-wired, label/icon/selectable propagated to the Type's CmdbLocations,
    MDS field changes and the flat field set applied to its CmdbObjects); because those mutate the
    document further, the response is a fresh read rather than the request payload

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        data (CmdbType.SCHEMA): New CmdbType data
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license; 404 when the Type does
            not exist, disappeared before the write, or cannot be read back afterwards; 400 when a
            guard refuses the change or the update, the location/MDS/object propagation fails;
            500 on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbType
    """
    # pylint: disable=too-many-statements  # complex update orchestration (re-reads + side effects)
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        old_type: CmdbType = get_type_instance_or_404(types_manager, public_id)

        # Editing an IPAM special type (existing or attempted) requires a valid IPAM license
        enforce_special_type_license(request_user, old_type.special_type, data.get(TypeSchemaKey.SPECIAL_TYPE))

        # Applied before CmdbType.from_data below, so the coercion reaches the instance too. Keyed on
        # the STORED marker: the SpecialType of a type can never change (guarded further down)
        enforce_rack_selectable_as_parent(old_type.special_type, data)

        data[TypeSchemaKey.LAST_EDIT_TIME] = datetime.now(timezone.utc)
        data[TypeSchemaKey.EDITOR_ID] = request_user.public_id
        # Pin the identity to the URL: a payload public_id can never rewrite the document's id
        data[TypeSchemaKey.PUBLIC_ID] = public_id
        new_type: CmdbType = CmdbType.from_data(data)

        if not special_type_is_unchanged(old_type.special_type, data.get(TypeSchemaKey.SPECIAL_TYPE)):
            abort(400, "It is not possible to change the SpecialType property of Types!")

        # Block removal of the location field while CmdbObjects still hold a location value
        guard_location_field_removal(request_user, old_type, new_type)

        # Block disabling selectable_as_parent while CmdbObjects of this Type are placed in the tree
        guard_selectable_as_parent_change(request_user, old_type, new_type)

        # Compute templates being removed by comparing the pre-update state to the incoming
        # payload (NOT the post-update type) and snapshot each removed template's section info
        # while it is still present on old_type - the blind update below wipes those sections
        removed_templates = compute_removed_global_templates(
            old_type, set(data.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS) or []),
        )

        # Update the target CmdbType. The write is a full-document update that does not upsert, so
        # matched_count reports whether the Type was still there - no extra read needed for that
        update_result: UpdateResult = types_manager.update_type(public_id, CmdbType.to_json(new_type))

        if update_result.matched_count == 0:
            LOGGER.warning(
                "[update_cmdb_type] Type with ID:%s disappeared between its read and its update", public_id
            )
            abort(404, f"The Type with ID:{public_id} no longer existed when its update was written!")

        # Run the post-update persistence side effects (template cleanup, special-type wiring,
        # location + MDS propagation). new_type IS what was just written, so it is used directly
        # instead of reading the document back
        apply_type_update_side_effects(request_user, types_manager, old_type, new_type, removed_templates)

        # Re-read the fully-persisted Type so server-side mutations applied by those side effects
        # (special-type ref_types cross-wiring, removed-template section cleanup) are reflected in
        # the response instead of the raw request payload
        final_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if not final_type:
            abort(404, f"The updated Type with ID:{public_id} could not be read back after its update!")

        return UpdateSingleResponse(final_type).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] LocationsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the update of Locations failed!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the update of correspondings Objects failed!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to check location-field usage for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except TypesManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Type with ID: {public_id} from the database!")
    except TypesManagerUpdateMDSError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerUpdateMDSError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the Multi-Data-Section updates failed!")
    except Exception as err:
        LOGGER.error("[update_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured when trying to update the Type with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.DELETE.value)
def delete_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbType

    Requires the ``base.framework.type.delete`` right and ApiLevel.ADMIN. A CmdbType may only be
    deleted while nothing depends on it: the deletion is refused when CmdbObjects of the Type exist
    or a CmdbReport uses it. Afterwards the follow-up removes the Type from the categories, the
    object groups and (for a SpecialType) its IPAM wiring

    Args:
        public_id (int): public_id of the CmdbType which should be deleted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license; 404 when no Type with
            that public_id exists; 400 when CmdbObjects or CmdbReports still use the Type, or a
            lookup / the deletion fails; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbType data
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        to_delete_type: dict[str, Any] | None = types_manager.get_type(public_id)

        # Deleting an IPAM special type requires a valid IPAM license
        enforce_special_type_license(
            request_user,
            to_delete_type.get(TypeSchemaKey.SPECIAL_TYPE) if to_delete_type else None,
        )

        # Check CmdbType is allowed to be deleted
        verify_type_deletable(request_user, public_id, to_delete_type)

        # Delete the CmdbType
        types_manager.delete_type(public_id)

        # All the followup actions where the public_id need to be removed
        type_deletion_followup(request_user, public_id, to_delete_type.get(TypeSchemaKey.SPECIAL_TYPE))
        return DeleteSingleResponse(to_delete_type).make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[delete_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id}!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")
    except BaseManagerGetError as err:
        LOGGER.error("[delete_cmdb_type] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to count Reports with this Type!")
    except TypesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_type] TypesManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_type] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, f"An internal server error occured while deleting Type with ID: {public_id}!")

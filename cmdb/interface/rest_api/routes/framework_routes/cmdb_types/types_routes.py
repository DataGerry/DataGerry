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

    POST   /                                insert_cmdb_type
    GET    /                                get_cmdb_types
    GET    /overview                        get_cmdb_types_overview
    GET    /<public_id>                     get_cmdb_type
    GET    /count_objects/<public_id>       count_objects_of_cmdb_type
    GET    /location_field_usage/<public_id> get_location_field_usage_of_cmdb_type
    PUT    /<public_id>                     update_cmdb_type
    PATCH  /<public_id>                     update_cmdb_type
    DELETE /<public_id>                     delete_cmdb_type

All routes require authentication (JWT or ``x-api-key`` in cloud mode), ApiLevel.ADMIN and the
per-route ``base.framework.type.*`` right (see ``TypeRight``). Domain logic lives in
``TypesManager`` and ``types_helper``; manager-layer errors map to HTTP 400 (business-rule /
lookup failures) or HTTP 500 (unexpected), following the codebase convention - 409 is not used.
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort, request
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

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@types_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.ADD.value)
@types_blueprint.validate(CmdbType.SCHEMA)
def insert_cmdb_type(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbType into the database

    Args:
        data (CmdbType.SCHEMA): Data of the CmdbType which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

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

    Args:
        params (CollectionParameters): Filter for requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetMultiResponse: All the CmdbTypes matching the CollectionParameters
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
    single bulk query)

    Args:
        params (TypeIterationParameters): Filter/pagination for the requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

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

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): CmdbUser requesting this data

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

    Args:
        public_id (int): The public_id of the CmdbType to count CmdbObjects for
        request_user (CmdbUser): CmdbUser requesting this data

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
    except ObjectsManagerGetError as err:
        LOGGER.error("[count_objects_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[count_objects_of_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while counting Objects for Type with ID: {public_id}!")


@types_blueprint.route('/location_field_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def get_location_field_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns the public_ids of CmdbObjects that have a value (integer > 0) in the
    location-typed field of the given CmdbType

    The frontend uses this to decide whether the location field can be removed
    from the CmdbType. The same check is enforced server-side on update

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

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
        LOGGER.error("[get_location_field_usage_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to determine location-field usage for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[get_location_field_usage_of_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error(
            "[get_location_field_usage_of_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True
        )
        abort(
            500,
            f"An internal server error occured while determining location-field usage for Type with ID: {public_id}!"
        )


@types_blueprint.route('/selectable_as_parent_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
def get_selectable_as_parent_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns whether the given CmdbType still has placed CmdbObjects, blocking a selectable-as-parent
    change to false

    The frontend uses this to decide whether the 'selectable_as_parent' toggle may be turned off:
    it may not while any CmdbObject of this Type is placed in the location tree (holds a location
    value > 0). The same check is enforced server-side on update by guard_selectable_as_parent_change

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

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
        LOGGER.error("[get_selectable_as_parent_usage_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to determine selectable-as-parent usage for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[get_selectable_as_parent_usage_of_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error(
            "[get_selectable_as_parent_usage_of_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True
        )
        abort(
            500,
            "An internal server error occured while determining selectable-as-parent usage "
            f"for Type with ID: {public_id}!"
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

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        data (CmdbType.SCHEMA): New CmdbType data
        request_user (CmdbUser): CmdbUser requesting this data

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

        # Update the target CmdbType
        types_manager.update_type(public_id, CmdbType.to_json(new_type))

        updated_type: CmdbType | None = types_manager.get_type_instance(public_id)

        if not updated_type:
            abort(404, f"The updated Type with ID:{public_id} was not found!")

        # Run the post-update persistence side effects (template cleanup, special-type wiring,
        # location + MDS propagation)
        apply_type_update_side_effects(request_user, types_manager, old_type, updated_type, removed_templates)

        # Re-read the fully-persisted Type so server-side mutations applied after the initial
        # update (special-type ref_types cross-wiring, removed-template section cleanup) are
        # reflected in the response instead of the raw request payload
        final_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if not final_type:
            abort(404, f"The updated Type with ID:{public_id} was not found!")

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

    Args:
        public_id (int): public_id of the CmdbType which should be deleted
        request_user (CmdbUser): CmdbUser requesting this data

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

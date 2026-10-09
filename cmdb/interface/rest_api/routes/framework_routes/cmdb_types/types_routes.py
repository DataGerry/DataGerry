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
    GET    /referenced_section_usage/<public_id>    get_referenced_section_usage_of_cmdb_type
    GET    /uses_ports_usage/<public_id>            get_uses_ports_usage_of_cmdb_type
    PUT    /<public_id>                             update_cmdb_type
    PATCH  /<public_id>                             update_cmdb_type
    DELETE /<public_id>                             delete_cmdb_type

All routes require authentication (JWT or ``x-api-key`` in cloud mode), ApiLevel.ADMIN and the
per-route ``base.framework.type.*`` right (see ``TypeRight``). Domain logic lives in
``TypesManager`` and ``types_helper``; manager-layer errors map to HTTP 400 (business-rule /
lookup failures) or HTTP 500 (unexpected), following the codebase convention - 409 is not used.

**Access control**: the two listing routes are additionally filtered by the type ACL. ``GET /types/``
filters to the types the caller's group holds the requested permissions on (``?acl=``, default READ);
``/types/overview`` always uses READ. The single-type read and the write routes are **not** -
a type filtered out of the listing can still be fetched, edited and deleted by public_id. The
listings matter most because their only access control is a filter the Angular app posts, which any
other API consumer can simply omit.
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort, request
from pymongo.results import UpdateResult
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import TypesManager, ObjectsManager, UsersManager, SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.framework.results import IterationResult
from cmdb.interface.route_utils import (
    abort_if_query_too_slow,
    abort_if_too_large,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.responses.response_parameters import ParameterKey
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    build_referenced_section_usage_payload,
    guard_referenced_section_removal,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_structure_helper import (
    guard_field_defaults,
    guard_new_identifiers,
    guard_type_structure,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    normalize_type_acl,
    verify_type_is_unique,
    prepare_builder_parameters,
    verify_type_deletable,
    count_objects_of_type,
    type_deletion_followup,
    special_type_is_unchanged,
    build_location_usage_payload,
    get_type_or_404,
    get_type_instance_or_404,
    abort_unless_type_readable,
    guard_field_identifier_change,
    guard_location_field_removal,
    guard_mds_section_identifier_change,
    guard_selectable_as_parent_change,
    guard_uses_ports_change,
    build_uses_ports_usage_payload,
    compute_removed_global_templates,
    apply_type_update_side_effects,
    strip_removed_global_templates,
    build_types_overview_items,
    enforce_special_type_license,
    enforce_rack_selectable_as_parent,
    enforce_uses_ports_license,
    normalize_port_section_index,
    normalize_ci_explorer_label,
)
from cmdb.framework.ipam.special_type_wiring import handle_special_types
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_template_helper import (
    reconcile_global_template_copies,
)
from cmdb.class_schema.write_schema_helper import build_write_schema
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

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import TYPE_ALIGNMENT_FAILED_MESSAGE

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.types_manager import (
    TypesManagerAlignmentError,
    TypesManagerGetError,
    TypesManagerInsertError,
    TypesManagerDeleteError,
    TypesManagerIterationError,
    TypesManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

types_blueprint = APIBlueprint('types', __name__)

# The request schema of the type writes: the identity and the alignment marker are the server's
TYPE_WRITE_SCHEMA: dict[str, Any] = build_write_schema(
    CmdbType.SCHEMA, server_owned={CmdbType.PUBLIC_ID_KEY, TypeSchemaKey.ALIGNMENT_PENDING.value},
)

# What each pre-check route is determining, interpolated into its failure messages
LOCATION_FIELD_USAGE_SUBJECT: str = 'location-field usage'
REFERENCED_SECTION_USAGE_SUBJECT: str = 'reference-section usage'
USES_PORTS_USAGE_SUBJECT: str = 'port usage'

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@types_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.ADD.value)
@types_blueprint.validate(TYPE_WRITE_SCHEMA)
@handle_route_errors("while creating the new Type")
def insert_cmdb_type(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbType into the database

    Requires the ``base.framework.type.add`` right and ApiLevel.ADMIN. The author and the creation
    time are stamped server-side, the ``acl`` block is completed to the shape every other write path
    stores, a duplicate type name is refused, and for a SpecialType the IPAM license is checked and
    the SpecialType wiring (ref_types cross-wiring, predefined sections) runs before the response is
    built. The payload's copy of each global section template it claims is put back in line with the stored
    template first (``reconcile_global_template_copies``), so every guard judges what will be stored

    Note:
        A payload ``public_id`` is currently honoured - the database only generates one when the key
        is absent - so a client can choose the new Type's id

    Args:
        data (CmdbType.SCHEMA): Data of the CmdbType which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license; 400 when the payload
            carries no name, the name is already taken, a claimed global template's section holds a field the
            template does not own, or the insert fails; 404 when the created
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

        # Declaring a Type as port-bearing requires a valid IPAM license
        enforce_uses_ports_license(request_user, data.get(TypeSchemaKey.USES_PORTS))

        # The copy of each claimed global section template is the template's - before any guard judges the payload
        reconcile_global_template_copies(data, request_user)

        # Where the frontend draws the ports section. Completed here for the same reason the ACL is:
        # the insert stores the payload as given, so an absent key would stay absent
        normalize_port_section_index(data)

        # 'ci_explorer_label' names one of the Type's own fields - the one whose value the CI
        # Explorer shows on every node of the Type - so a name the Type does not offer is refused
        normalize_ci_explorer_label(data)

        # Every identifier of a new Type is new: none may be blank, padded or bracketed (type_identifier_rules)
        guard_new_identifiers(data)

        # The sections and the summary line only REFERENCE the fields the flat list declares, and
        # nothing downstream re-checks that pairing - a payload that breaks it is stored as sent and
        # yields a Type that holds fields and renders none of them, or a summary line that drops
        # the entry it was configured to show
        guard_type_structure(data)

        # A field's default is what every new object starts from, so it has to pass the field's own rules
        guard_field_defaults(data)

        data.setdefault(TypeSchemaKey.CREATION_TIME, datetime.now(timezone.utc))
        data[TypeSchemaKey.AUTHOR_ID] = request_user.public_id

        # The insert stores the payload as given, so the ACL is completed here - an update and an
        # import get the same block for free by going through the model
        normalize_type_acl(data)

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
    except TypesManagerGetError as err:
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to retrieve the created Type from the database!")
    except TypesManagerInsertError as err:
        abort_if_too_large(err)
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to insert the new Type into the database!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@types_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@types_blueprint.parse_parameters(TypeIterationParameters)
@handle_route_errors("while retrieving the Types")
def get_cmdb_types(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbTypes

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN, and the listing is
    additionally restricted to the CmdbTypes the requesting user's group may access under the type
    ACL - the right decides whether the screen opens at all, the ACL decides what is in it.

    ``?acl=`` names the permission that restriction asks about, defaulting to READ. It **replaces**
    READ rather than adding to it, so ``?acl=CREATE`` answers "the types my group may create an
    object of", and ``?acl=READ,CREATE`` requires both. Every route that addresses one type by id
    refuses a type the group may not READ (403), so what this listing hides by default is hidden
    everywhere.

    ``?category=<public_id>`` restricts the listing to the CmdbTypes assigned to that CmdbCategory
    and ``?uncategorized=true`` to the CmdbTypes assigned to none; the two cannot be combined

    Args:
        params (TypeIterationParameters): Filter, sort, pagination, the 'active' flag, the category
            filters and the requested ACL permissions for the requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the iteration fails; 500 on an unexpected error

    Returns:
        GetMultiResponse: All the CmdbTypes matching the TypeIterationParameters
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        builder_params: BuilderParameters = prepare_builder_parameters(params, request_user)

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(
            builder_params,
            request_user,
            params.acl,
        )
        types: list[dict[str, Any]] = [CmdbType.to_json(type) for type in iteration_result.results]

        api_response = GetMultiResponse(
            types,
            total=iteration_result.total,
            params=params,
            url=request.url,
            body=request_wants_body()
        )

        return api_response.make_response()
    except TypesManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_types] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")


@types_blueprint.route('/overview', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@types_blueprint.parse_parameters(TypeIterationParameters)
@handle_route_errors("while retrieving the Types overview")
def get_cmdb_types_overview(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the types overview listing

    Returns the filtered CmdbTypes each bundled with its resolved author/editor display block, so
    the overview renders author/editor names without a per-type user lookup (they are resolved in a
    single bulk query). Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN, and is
    restricted to the CmdbTypes the requesting user's group may READ under the type ACL - the same
    rule the plain listing applies, so the two never disagree about what exists.

    Unlike ``GET /types/`` this route does **not** take ``?acl=``: it is the type administration
    table and nothing asks it for another permission. A caller that sends one is refused rather than
    quietly served a READ listing, because a parameter that is accepted and ignored is worse than
    one that does not exist

    Args:
        params (TypeIterationParameters): Filter/pagination for the requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when ``?acl=`` asks for anything but READ or when the iteration fails;
            500 on an unexpected error

    Returns:
        GetMultiResponse: The matching CmdbTypes, each as a {type_data, user_data} item
    """
    try:
        if params.acl != [AccessControlPermission.READ]:
            abort(400, f"The Types overview cannot be filtered by '{ParameterKey.ACL.value}'!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        builder_params: BuilderParameters = prepare_builder_parameters(params, request_user)

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(
            builder_params,
            request_user,
            AccessControlPermission.READ,
        )
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
            body=request_wants_body()
        )

        return api_response.make_response()
    except TypesManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_types_overview] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")


@types_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@handle_route_errors("while retrieving Type with ID:{public_id}")
def get_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbType

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN, and READ on the Type's ACL - the
    same rule the listings apply, so a Type the listing hides cannot be fetched by its public_id either

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 403 when the caller's group may not
            READ it; 400 when the read fails; 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        requested_type: dict[str, Any] = get_type_or_404(types_manager, public_id)
        abort_unless_type_readable(requested_type, request_user)

        return GetSingleResponse(requested_type, body=request_wants_body()).make_response()
    except TypesManagerGetError as err:
        LOGGER.error("[get_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")


@types_blueprint.route('/count_objects/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@handle_route_errors("while counting Objects for Type with ID: {public_id}")
def count_objects_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Counts the CmdbObjects of a CmdbType - the pre-check of the Type delete

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. The delete refuses a Type that still
    has CmdbObjects (``verify_type_deletable``); this route answers the same question through the same count
    (``count_objects_of_type``), so the number the delete page shows is the one the delete acts on: every
    CmdbObject of the Type, active or not. A missing Type is not an error - it simply has no objects, so
    the count is 0

    A Type the caller's group may not READ is refused (403), like every route on one Type. The count of a
    readable Type is the total: an ACL lives on the Type, so its CmdbObjects are readable all or none

    Args:
        public_id (int): The public_id of the CmdbType to count CmdbObjects for
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the caller's group may not READ the Type; 400 when the Type cannot be read or
            the count fails; 500 on an unexpected error

    Returns:
        DefaultResponse: An API response containing the count of CmdbObjects for the given type_id
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        counted_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if counted_type:
            abort_unless_type_readable(counted_type, request_user)

        return DefaultResponse(count_objects_of_type(objects_manager, public_id)).make_response()
    except TypesManagerGetError as err:
        LOGGER.error("[count_objects_of_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[count_objects_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")


@types_blueprint.route('/location_field_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@handle_route_errors(f"while determining {LOCATION_FIELD_USAGE_SUBJECT} for Type with ID: {{public_id}}")
def get_location_field_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns the public_ids of CmdbObjects that have a value (integer > 0) in the
    location-typed field of the given CmdbType

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. It answers the pre-check of
    **both** location guards on update, because both ask whether any object of the Type is placed in
    the location tree: removing the location field (guard_location_field_removal - the frontend's
    ``type.service.ts`` calls this route for it) and turning 'selectable_as_parent' off
    (guard_selectable_as_parent_change). A Type the caller's group may not READ is refused

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 403 when the caller's group may not
            READ it; 400 when the Type or its CmdbObjects could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, count: int, object_public_ids: list[int] }
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        target_type: CmdbType = get_type_instance_or_404(types_manager, public_id)
        abort_unless_type_readable(target_type, request_user)

        return DefaultResponse(build_location_usage_payload(request_user, target_type)).make_response()
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_location_field_usage_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to determine {LOCATION_FIELD_USAGE_SUBJECT} for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[get_location_field_usage_of_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")


@types_blueprint.route('/referenced_section_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@handle_route_errors(f"while determining {REFERENCED_SECTION_USAGE_SUBJECT} for Type with ID: {{public_id}}")
def get_referenced_section_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns which CmdbTypes reference the given CmdbType, and which of its sections they pull

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. A section may only be removed
    (or renamed - a ref-section resolves its target by NAME) once no other CmdbType pulls its fields
    through a reference section, and the Type itself may only be deleted once nothing references it at
    all. Both are enforced server-side by guard_referenced_section_removal and verify_type_deletable;
    this route exists so the type builder can disable the delete action up front instead of learning
    about it from a 400.

    ``sections`` is keyed by section name and carries only the sections that ARE referenced, so a
    section absent from it is free to remove. ``count`` and ``in_use`` count every referencing Type, since
    the guards refuse on all of them; ``referencing_type_ids`` and each section's list NAME only the ones the
    caller's group may READ, so a section referenced by hidden Types alone is present with an empty list

    A Type the caller's group may not READ is refused

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 403 when the caller's group may not
            READ it; 400 when the Type or the referencing Types could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, count: int, referencing_type_ids: list[int],
                           sections: { <section_name>: [{public_id, name, label}] } }
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        target_type: CmdbType = get_type_instance_or_404(types_manager, public_id)
        abort_unless_type_readable(target_type, request_user)

        payload = build_referenced_section_usage_payload(request_user, target_type)

        return DefaultResponse(payload).make_response()
    except TypesManagerGetError as err:
        LOGGER.error("[get_referenced_section_usage_of_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to determine {REFERENCED_SECTION_USAGE_SUBJECT} for Type with ID: {public_id}!")

@types_blueprint.route('/uses_ports_usage/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.VIEW.value)
@handle_route_errors(f"while determining {USES_PORTS_USAGE_SUBJECT} for Type with ID: {{public_id}}")
def get_uses_ports_usage_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns how many Ports exist on the CmdbObjects of the given CmdbType

    Requires the ``base.framework.type.view`` right and ApiLevel.ADMIN. A CmdbType may only stop using
    ports once none of its objects has one, because the frontend renders the ports panel for a
    port-bearing type only - the same check is enforced server-side on update by
    `guard_uses_ports_change`. ``in_use: false`` means the flag may be cleared.

    Counts only, deliberately: the equivalent location payload returns every matching public_id and is
    unbounded for a large Type.

    Note this read is NOT license-gated, unlike the rest of the feature. Turning the flag off is the
    cleanup direction and is always allowed, so gating the pre-check would blind exactly the users who
    need it after a license lapsed. A Type the caller's group may not READ is refused

    Args:
        public_id (int): public_id of the CmdbType to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when no Type with that public_id exists; 403 when the caller's group may not
            READ it; 400 when the Type, its Objects or their Ports could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, port_count: int, object_count: int }
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        target_type: CmdbType = get_type_instance_or_404(types_manager, public_id)
        abort_unless_type_readable(target_type, request_user)

        return DefaultResponse(build_uses_ports_usage_payload(request_user, target_type)).make_response()
    except (ObjectsManagerGetError, TypesManagerGetError) as err:
        LOGGER.error("[get_uses_ports_usage_of_cmdb_type] ManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to determine {USES_PORTS_USAGE_SUBJECT} for Type with ID: {public_id}!")


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.EDIT.value)
@types_blueprint.validate(TYPE_WRITE_SCHEMA)
@handle_route_errors("when trying to update the Type with ID: {public_id}")
def update_cmdb_type(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbType

    Requires the ``base.framework.type.edit`` right and ApiLevel.ADMIN, and READ on the STORED Type's ACL:
    a group the ACL hides a Type from may not edit it - nor rewrite that ACL to let itself in. The write is
    always a full document (there is no partial update): the editor and the edit time are stamped server-side, the
    identity is pinned to the URL public_id, and several changes are refused outright - changing the
    SpecialType, renaming a field or a multi-data-section identifier while the Type has Objects,
    removing the location field while CmdbObjects still hold a location value, and turning
    'selectable_as_parent' off while CmdbObjects of the Type are placed in the tree

    Before any of that is judged, the payload's copy of each global section template it claims is put back in line
    with the stored template (``reconcile_global_template_copies``); a claim naming no stored template is dropped
    without counting as a removed template, so the section and fields it named stay

    The Type is written ONCE - with the dropped global templates already taken out of it and the
    server-owned ``alignment_pending`` marker set. Then the SpecialType ref_types are re-wired and the
    Type's CmdbLocations, the MDS rows and flat fields of its CmdbObjects and its CmdbReports are brought
    in line with it; only when all of that succeeded is the marker cleared. Every step is idempotent, and a
    Type that still carries the marker has every step run in full on its next save - so a save that
    failed half-way is finished by saving the Type again, the same payload included. The response is a
    fresh read of the stored Type

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        data (CmdbType.SCHEMA): New CmdbType data
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license, or the caller's group may not
            READ the stored Type; 404 when the Type does not exist, disappeared before the write, or cannot be
            read back afterwards; 400 when a guard refuses the change (a claimed global template's section
            holding a field the template does not own among them) or the Type write fails; 500 when a step
            after the write fails (the Type IS saved and carries ``alignment_pending``; the message names the
            step) or on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbType
    """
    # pylint: disable=too-many-statements  # complex update orchestration (re-reads + side effects)
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        old_type: CmdbType = get_type_instance_or_404(types_manager, public_id)

        # Judged on the stored ACL, never the payload's: the payload may carry a rewritten one
        abort_unless_type_readable(old_type, request_user)

        # Editing an IPAM special type (existing or attempted) requires a valid IPAM license
        enforce_special_type_license(request_user, old_type.special_type, data.get(TypeSchemaKey.SPECIAL_TYPE))

        # Applied before CmdbType.from_data below, so the coercion reaches the instance too. Keyed on
        # the STORED marker: the SpecialType of a type can never change (guarded further down)
        enforce_rack_selectable_as_parent(old_type.special_type, data)

        # Turning 'uses_ports' on requires a valid IPAM license. Only the requested value is gated,
        # so an unlicensed instance can still turn the flag back off
        enforce_uses_ports_license(request_user, data.get(TypeSchemaKey.USES_PORTS))

        # The copy of each claimed global section template is the template's - before any guard judges the payload.
        # A claim it drops (no such template here) is not the user removing the template: it keeps its section
        dropped_claims: list[str] = reconcile_global_template_copies(data, request_user)

        # Applied before CmdbType.from_data below, so the validated (and, without ports, reset) index
        # is what reaches the instance that gets written
        normalize_port_section_index(data)

        # The CI Explorer label field, judged against THIS payload: an update that removes the
        # nominated field clears the nomination instead of being refused over it
        normalize_ci_explorer_label(data, old_type)

        # The identifiers this update ADDS follow the identifier rule; the stored ones are immutable and pass
        guard_new_identifiers(data, old_type)

        # An update writes the whole document, so it can introduce the same inconsistency a create
        # can: sections or a summary line referencing fields the payload does not declare
        guard_type_structure(data)

        # Same default rule as the create - a Type stored with a bad default is refused until it is fixed
        guard_field_defaults(data)

        data[TypeSchemaKey.LAST_EDIT_TIME] = datetime.now(timezone.utc)
        data[TypeSchemaKey.EDITOR_ID] = request_user.public_id
        pin_public_id(data, public_id)
        new_type: CmdbType = CmdbType.from_data(data)

        if not special_type_is_unchanged(old_type.special_type, data.get(TypeSchemaKey.SPECIAL_TYPE)):
            abort(400, "It is not possible to change the SpecialType property of Types!")

        # A field's name IS its identity - every CmdbObject keys its stored values by it - so a
        # rename would empty that value on every Object. Same for a multi-data-section, whose name is
        # the section_id an Object stores its rows under: a rename drops every row
        guard_field_identifier_change(request_user, old_type, new_type)
        guard_mds_section_identifier_change(request_user, old_type, new_type)

        # Block removal of the location field while CmdbObjects still hold a location value
        guard_location_field_removal(request_user, old_type, new_type)

        # A section another Type pulls its fields from may not be removed (or renamed) while
        # that Type still references it - the reference resolves by NAME and would be left dangling
        guard_referenced_section_removal(request_user, old_type, new_type)

        # Block disabling selectable_as_parent while CmdbObjects of this Type are placed in the tree
        guard_selectable_as_parent_change(request_user, old_type, new_type)

        # Block disabling uses_ports while Ports of this Type's Objects still exist - clearing the flag
        # hides the ports panel, so those ports would become rows nothing in the UI can reach
        guard_uses_ports_change(request_user, old_type, new_type)

        # Compute templates being removed by comparing the pre-update state to the incoming
        # payload (NOT the post-update type) and snapshot each removed template's section info
        # while it is still present on old_type - the blind update below wipes those sections
        removed_templates = compute_removed_global_templates(
            old_type, set(data.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS) or []) | set(dropped_claims),
        )

        # The one write of the Type: the dropped templates already taken out of it, and the alignment marker set -
        # cleared again only once everything that follows the Type is in line with it, so a save that fails
        # half-way shows on the Type and its next save finishes the work
        type_document: dict[str, Any] = strip_removed_global_templates(CmdbType.to_json(new_type), removed_templates)
        type_document[TypeSchemaKey.ALIGNMENT_PENDING.value] = True
        written_type: CmdbType = CmdbType.from_data(type_document)

        # A full-document update that does not upsert, so matched_count reports whether the Type was still there
        update_result: UpdateResult = types_manager.update_type(public_id, type_document)

        if update_result.matched_count == 0:
            LOGGER.warning(
                "[update_cmdb_type] Type with ID:%s disappeared between its read and its update", public_id
            )
            abort(404, f"The Type with ID:{public_id} no longer existed when its update was written!")

        # Bring the SpecialType wiring, the Locations, the Objects and the Reports in line with it, then clear the
        # marker. written_type IS what was just written, so it is used directly instead of reading it back
        apply_type_update_side_effects(request_user, types_manager, old_type, written_type)

        # Re-read the fully-persisted Type so server-side mutations applied by those side effects
        # (special-type ref_types cross-wiring, removed-template section cleanup) are reflected in
        # the response instead of the raw request payload
        final_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if not final_type:
            abort(404, f"The updated Type with ID:{public_id} could not be read back after its update!")

        return UpdateSingleResponse(final_type).make_response()
    except TypesManagerAlignmentError as err:
        # The Type IS saved and carries alignment_pending: one answer for whichever step failed
        abort(500, TYPE_ALIGNMENT_FAILED_MESSAGE.format(public_id=public_id, step=err.step))
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to check location-field usage for Type with ID: {public_id}!")
    except TypesManagerGetError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except TypesManagerUpdateError as err:
        abort_if_too_large(err)
        LOGGER.error("[update_cmdb_type] TypesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Type with ID: {public_id} from the database!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right=TypeRight.DELETE.value)
@handle_route_errors("while deleting Type with ID: {public_id}")
def delete_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbType

    Requires the ``base.framework.type.delete`` right and ApiLevel.ADMIN, and READ on the Type's ACL. A
    CmdbType may only be deleted while nothing depends on it: the deletion is refused when CmdbObjects of the Type exist
    or a CmdbReport uses it. Afterwards the follow-up removes the Type from the categories, the
    object groups and (for a SpecialType) its IPAM wiring

    Args:
        public_id (int): public_id of the CmdbType which should be deleted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license, or the caller's group may not
            READ the Type; 404 when no Type with that public_id exists; 400 when CmdbObjects or CmdbReports still
            use the Type, or a lookup / the deletion fails; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbType data
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        to_delete_type: dict[str, Any] | None = types_manager.get_type(public_id)

        # A missing Type is the 404 of verify_type_deletable below
        if to_delete_type:
            abort_unless_type_readable(to_delete_type, request_user)

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

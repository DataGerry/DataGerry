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
Definition of all routes for CmdbSectionTemplates

A CmdbSectionTemplate is a section definition that CmdbTypes can adopt. A GLOBAL one stays linked: the
consuming types reference it and a change here is propagated into every one of them, and into their
objects. That link is by **name** - ``global_template_ids`` on the type, ``get_types_using_template`` on
the way back - which is why the name is immutable once the template exists

PREDEFINED templates are DataGerry's own. They are seeded and propagated programmatically, so this
route refuses to create, edit or delete one; only the seeding code touches them

Both write paths propagate in two steps and are NOT atomic: the update writes the template and then
reconciles the consuming types, the delete cleans the consumers and then removes the document. A failure
in between is reported as a partial application rather than as a failed request, so the caller knows the
halves disagree
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import SectionTemplatesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import (
    SectionTemplateKey,
    SectionTemplateRight,
)
from cmdb.models.type_model import SectionType
from cmdb.framework.results import IterationResult
from cmdb.framework.section_templates.virtual_section_templates import (
    VIRTUAL_TEMPLATE_NAME_PREFIX,
    get_virtual_section_templates,
    is_virtual_template_name,
)
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import UpdateSingleResponse, GetMultiResponse, DefaultResponse
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper import (
    require_params,
    guard_section_template_update,
    parse_json_fields,
    coerce_bool,
    coerce_public_id,
)

from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerInsertError,
    SectionTemplatesManagerIterationError,
    SectionTemplatesManagerGetError,
    SectionTemplatesManagerUpdateError,
    SectionTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

section_template_blueprint = APIBlueprint('section_templates', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@section_template_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.ADD.value)
@section_template_blueprint.parse_request_parameters()
def create_section_template(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates a CmdbSectionTemplate from the request body

    Requires the ``base.framework.sectionTemplate.add`` right

    Rejects a duplicate name, an invalid section type, or an attempt to create a predefined template via
    the API; assigns the next public_id and normalizes the boolean / JSON-encoded body fields before
    insert. The name has to be free because it is the key consuming types reference the template by, and
    it can not be changed afterwards

    Args:
        params (dict[str, Any]): Request body carrying 'name', 'label', 'type', 'is_global',
            'predefined' and a JSON-encoded 'fields' list
        request_user (CmdbUser): The user making the request (auth / manager scoping)

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when a parameter is missing or malformed,
            the name is taken, the type is not a section type, 'predefined' is requested, or the insert
            fails; 500 on an unexpected error

    Returns:
        Response: DefaultResponse wrapping the public_id of the created CmdbSectionTemplate
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        require_params(params, [
            SectionTemplateKey.NAME,
            SectionTemplateKey.LABEL,
            SectionTemplateKey.TYPE,
            SectionTemplateKey.IS_GLOBAL,
            SectionTemplateKey.PREDEFINED,
            SectionTemplateKey.FIELDS,
        ])

        template_name: str = params[SectionTemplateKey.NAME]
        existing_template: dict[str, Any] | None = section_templates_manager.get_one_by(
            {SectionTemplateKey.NAME: template_name},
        )

        if existing_template:
            abort(400, f"A template with the name: {template_name} already exists!")

        # The virtual-template name space is reserved: a stored template carrying such a name would
        # shadow the virtual one for every frontend that resolves templates by name
        if is_virtual_template_name(template_name):
            abort(400, f"The name prefix '{VIRTUAL_TEMPLATE_NAME_PREFIX}' is reserved for virtual "
                       "section templates!")

        if params[SectionTemplateKey.TYPE] not in [SectionType.SECTION, SectionType.MDS_SECTION]:
            abort(400, f"Invalid template type provided: {params[SectionTemplateKey.TYPE]}!")

        if coerce_bool(params[SectionTemplateKey.PREDEFINED]):
            abort(400, "It is not possible to create predefined section templates via API!")

        params[SectionTemplateKey.PUBLIC_ID] = section_templates_manager.get_next_public_id(inc_id=True)
        params[SectionTemplateKey.IS_GLOBAL] = coerce_bool(params[SectionTemplateKey.IS_GLOBAL])
        params[SectionTemplateKey.PREDEFINED] = False
        params[SectionTemplateKey.FIELDS] = parse_json_fields(params[SectionTemplateKey.FIELDS])

        created_section_template_id: int = section_templates_manager.insert_section_template(params)

        return DefaultResponse(created_section_template_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerInsertError as err:
        LOGGER.error("[create_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to create the SectionTemplate!")
    except Exception as err:
        LOGGER.error("[create_section_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while creating the SectionTemplate!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@section_template_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.VIEW.value)
@section_template_blueprint.parse_collection_parameters(view='native')
def get_all_section_templates(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns a paginated collection of CmdbSectionTemplates matching the query parameters

    Requires the ``base.framework.sectionTemplate.view`` right

    Args:
        params (CollectionParameters): Pagination / filter / sort parameters
        request_user (CmdbUser): The user making the request

    Returns:
        Response: GetMultiResponse with the matching CmdbSectionTemplates and the total count
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        builder_params: BuilderParameters = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbSectionTemplate] = section_templates_manager.iterate(builder_params)
        template_list: list[dict[str, Any]] = [CmdbSectionTemplate.to_json(template_)
                                               for template_ in iteration_result.results]

        api_response = GetMultiResponse(
            template_list,
            iteration_result.total,
            params,
            request.url,
            request.method == 'HEAD'
        )

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerIterationError as err:
        LOGGER.error("[get_all_section_templates] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to iterate SectionTemplates!")
    except Exception as err:
        LOGGER.error("[get_all_section_templates] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating SectionTemplates!")


@section_template_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.VIEW.value)
def get_section_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves a single CmdbSectionTemplate by public_id

    Requires the ``base.framework.sectionTemplate.view`` right

    Args:
        public_id (int): public_id of the CmdbSectionTemplate to retrieve
        request_user (CmdbUser): The user making the request

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no template carries the public_id;
            400 when the read fails; 500 on an unexpected error

    Returns:
        Response: DefaultResponse wrapping the CmdbSectionTemplate document
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )
        section_template_instance: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not section_template_instance:
            abort(404, f"SectionTemplate with ID: {public_id} not found!")

        return DefaultResponse(CmdbSectionTemplate.to_json(section_template_instance)).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[get_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to retrieve SectionTemplate with public_id: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_section_template] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving SectionTemplate with ID: {public_id}!")


@section_template_blueprint.route('/<int:public_id>/count', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.VIEW.value)
def get_global_section_template_count(public_id: int, request_user: CmdbUser) -> Response:
    """
    Returns how many types and objects use a CmdbSectionTemplate (zero when it is not global)

    Requires the ``base.framework.sectionTemplate.view`` right. The frontend asks this before offering
    a delete, so the user is told what the deletion would touch

    Args:
        public_id (int): public_id of the CmdbSectionTemplate to inspect
        request_user (CmdbUser): The user making the request

    Returns:
        Response: DefaultResponse wrapping {'types': int, 'objects': int}; aborts 404 when the
            template does not exist
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        instance: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not instance:
            abort(404, f"Target SectionTemplate with ID:{public_id} not found")

        counts: dict[str, int] = section_templates_manager.get_global_template_usage_count(
            instance.name, instance.is_global,
        )

        return DefaultResponse(counts).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[get_global_section_template_count] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to retrieve global SectionTemplate count for ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_global_section_template_count] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
            f"An internal server error occured while retrieving global SectionTemplate count for ID: {public_id}!"
        )

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@section_template_blueprint.route('/virtual/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.IPAM)
def get_virtual_cmdb_section_templates(request_user: CmdbUser) -> Response:
    # request_user is not read here but must be in the signature: insert_request_user injects it and
    # requires_feature reads it out of kwargs to resolve the active license
    # pylint: disable=unused-argument
    """
    HTTP `GET`/`HEAD` route to retrieve the VIRTUAL section templates

    A virtual template looks like a global section template to the frontend but is never stored: it has
    no public_id, it is not in framework.sectionTemplates, and none of the other routes on this
    blueprint know about it - see cmdb.framework.section_templates.virtual_section_templates for why
    each of those matters.

    Gated per route rather than per blueprint, because the rest of this blueprint is not a licensed
    surface: `dg-virtual-tpl-ports` belongs to Port Connectivity, which is gated behind IPAM

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the IPAM license; 500 on an unexpected
            error

    Returns:
        DefaultResponse: The virtual section templates as a list
    """
    # No `except HTTPException: raise` guard here, unlike the other routes on this blueprint: nothing
    # inside the try aborts (the right and the license are checked by the decorators above it), so that
    # arm would be unreachable
    try:
        return DefaultResponse(get_virtual_section_templates()).make_response()
    except Exception as err:
        LOGGER.error("[get_virtual_cmdb_section_templates] Exception: %s. Type: %s", err, type(err),
                     exc_info=True)
        abort(500, "An internal server error occured while retrieving the virtual SectionTemplates!")


@section_template_blueprint.route('/', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.EDIT.value)
@section_template_blueprint.parse_request_parameters()
def update_section_template(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Updates a CmdbSectionTemplate and propagates the change to consuming types and objects

    Requires the ``base.framework.sectionTemplate.edit`` right

    The name is required and immutable: it is the key consuming types reference the template by, so the
    propagation is keyed on it. Requiring it is what makes the propagation unconditional - a payload
    without a name used to be accepted, written, and then propagated to nobody, reporting success

    The immutability rules live in ``guard_section_template_update``; the write and the propagation are
    two steps, so a propagation failure is reported as a partial application (the template is already
    updated) rather than as a failed request

    Args:
        params (dict[str, Any]): Request body - the updated template incl. 'public_id', 'name', 'label',
            'type', 'predefined', 'is_global' and a JSON-encoded 'fields' list
        request_user (CmdbUser): The user making the request

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when the template does not exist; 400 when
            a parameter is missing or malformed, the template is predefined or an immutable property
            would change, or the write fails; 500 on an unexpected error and on a failed propagation

    Returns:
        Response: UpdateSingleResponse(True)
    """
    public_id: int | None = None

    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        require_params(params, [
            SectionTemplateKey.PUBLIC_ID,
            SectionTemplateKey.NAME,
            SectionTemplateKey.LABEL,
            SectionTemplateKey.TYPE,
            SectionTemplateKey.IS_GLOBAL,
            SectionTemplateKey.PREDEFINED,
            SectionTemplateKey.FIELDS,
        ])

        params[SectionTemplateKey.PUBLIC_ID] = coerce_public_id(params[SectionTemplateKey.PUBLIC_ID])
        params[SectionTemplateKey.PREDEFINED] = coerce_bool(params[SectionTemplateKey.PREDEFINED])
        params[SectionTemplateKey.IS_GLOBAL] = coerce_bool(params[SectionTemplateKey.IS_GLOBAL])
        params[SectionTemplateKey.FIELDS] = parse_json_fields(params[SectionTemplateKey.FIELDS])

        public_id = params[SectionTemplateKey.PUBLIC_ID]
        current_template: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not current_template:
            abort(404, "Target section template not found!")

        guard_section_template_update(current_template, params)

        section_templates_manager.update_section_template(public_id, params)

        # Apply changes to all types and objects using the template. The template is already written, so
        # a failure here leaves the two halves disagreeing - say so instead of reporting a failed update
        try:
            section_templates_manager.handle_section_template_changes(params, current_template)
        except Exception as err:
            LOGGER.error("[update_section_template] Propagation failed: %s. Type: %s", err, type(err),
                         exc_info=True)
            abort(500,
                f"The SectionTemplate with ID: {public_id} was updated, but the change could not be "
                f"applied to the types using it!"
            )

        return UpdateSingleResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[update_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to retrieve SectionTemplate with ID: {public_id}!")
    except SectionTemplatesManagerUpdateError as err:
        LOGGER.error("[update_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to update SectionTemplate with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_section_template] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating SectionTemplate with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@section_template_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right=SectionTemplateRight.DELETE.value)
def delete_section_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes a CmdbSectionTemplate by its public_id

    Requires the ``base.framework.sectionTemplate.delete`` right. Registered WITHOUT a trailing slash,
    which is the form the frontend calls and the one its sibling read route uses - the slash-only
    registration answered every delete with a 308 first

    A predefined template is refused. For a global one the section is cleaned out of every consuming
    type and their objects BEFORE the document goes, because the cleanup is keyed on the template that
    still has to exist. The two steps are not atomic: a failed cleanup deletes nothing, while a failure
    after it is reported as a partial application

    Args:
        public_id (int): public_id of the CmdbSectionTemplate to delete
        request_user (CmdbUser): The user making the request (auth / manager scoping)

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when the template does not exist; 400 when
            it is predefined or a step fails; 500 on an unexpected error and when the consumers were
            cleaned but the template could not be removed

    Returns:
        Response: DefaultResponse wrapping the deletion acknowledgement
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        template_instance: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not template_instance:
            abort(404, f"Section Template with ID: {public_id} not found!")

        if template_instance.predefined:
            abort(400, "A predefined SectionTemplate is not deletable!")

        cleaned_up: bool = False

        if template_instance.is_global:
            # Runs first: it is keyed on the template, which still has to be there
            section_templates_manager.cleanup_global_section_templates(template_instance.name, True)
            cleaned_up = True

        try:
            ack: bool = section_templates_manager.delete_section_template(public_id)
        except Exception as err:
            if cleaned_up:
                LOGGER.error("[delete_section_template] Deletion after cleanup failed: %s. Type: %s",
                             err, type(err), exc_info=True)
                abort(500,
                    f"The SectionTemplate with ID: {public_id} was removed from the types using it, but "
                    f"the template itself could not be deleted!"
                )

            raise

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[delete_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to retrieve SectionTemplate with public_id: {public_id}!")
    except SectionTemplatesManagerDeleteError as err:
        LOGGER.error("[delete_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to delete SectionTemplate with public_id: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_section_template] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the SectionTemplate with ID:{public_id}!")

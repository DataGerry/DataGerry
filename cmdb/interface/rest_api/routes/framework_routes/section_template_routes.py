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
"""
import json
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
from cmdb.models.type_model import SectionType
from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import UpdateSingleResponse, GetMultiResponse, DefaultResponse

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
@section_template_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.add')
def create_section_template(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates a CmdbSectionTemplate in the database

    Args:
        params (dict): CmdbSectionTemplate parameters
    Returns:
        int: public_id of the created CmdbSectionTemplate
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        existing_template: dict[str, Any] | None = section_templates_manager.get_one_by({'name': params['name']})

        if existing_template:
            abort(400, f"A template with the name: {params['name']} already exists!")

        if params['type'] not in [SectionType.SECTION, SectionType.MDS_SECTION]:
            abort(400, f"Invalid template type provided: {params['type']}!")

        if params['predefined'] in ['true', 'True', True]:
            abort(400, "It is not possible to create predefined section templates via API!")

        params['public_id'] = section_templates_manager.get_next_public_id(inc_id=True)
        params['is_global'] = params['is_global'] in ['true', 'True', True]
        params['predefined'] = False
        params['fields'] = json.loads(params['fields'])

        created_section_template_id: int = section_templates_manager.insert_section_template(params)

        return DefaultResponse(created_section_template_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerInsertError as err:
        LOGGER.error("[create_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to create the SectionTemplate!")
    except Exception as err:
        LOGGER.error("[create_section_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while creating the SectionTemplate!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@section_template_blueprint.route('/', methods=['GET', 'HEAD'])
@section_template_blueprint.parse_collection_parameters(view='native')
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.view')
def get_all_section_templates(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns all CmdbSectionTemplates based on the params

    Args:
        params (CollectionParameters): Parameters to identify documents in database
    Returns:
        (GetMultiResponse): All CmdbSectionTemplates considering the params
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        builder_params: BuilderParameters = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbSectionTemplate] = section_templates_manager.iterate(builder_params)
        template_list: list[dict] = [template_.__dict__ for template_ in iteration_result.results]

        api_response = GetMultiResponse(
            template_list,
            iteration_result.total,
            params,
            request.url,
            request.method == 'HEAD'
        )

        return api_response.make_response()
    except SectionTemplatesManagerIterationError as err:
        LOGGER.error("[get_all_section_templates] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to iterate SectionTemplates!")
    except Exception as err:
        LOGGER.error("[get_all_section_templates] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating SectionTemplates!")


@section_template_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.view')
def get_section_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the CmdbSectionTemplate with the given public_id
    
    Args:
        public_id (int): public_id of CmdbSectionTemplate which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbSectionTemplate
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )
        section_template_instance: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not section_template_instance:
            abort(404, f"SectionTemplate with ID: {public_id} not found!")

        return DefaultResponse(section_template_instance).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[get_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve SectionTemplate with public_id: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_all_section_templates] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving SectionTemplate with ID: {public_id}!")


@section_template_blueprint.route('/<int:public_id>/count', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.view')
def get_global_section_template_count(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrives the count of types and objects using this global CmdbSectionTemplate

    Args:
        public_id (int): public_id of CmdbSectionTemplate which should be checked
    Returns:
        dict: Dict with counts of types and objects using this global CmdbSectionTemplate
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        instance: CmdbSectionTemplate = section_templates_manager.get_section_template(public_id)

        if not instance:
            abort(404, f"Target SectionTemplate with ID:{public_id} not found")

        counts: dict = section_templates_manager.get_global_template_usage_count(instance.name, instance.is_global)

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

@section_template_blueprint.route('/', methods=['PUT', 'PATCH'])
@section_template_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.edit')
def update_section_template(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Updates a CmdbSectionTemplate

    Args:
        params (dict): updated CmdbSectionTemplate parameters
    Returns:
        bool: success
    """
    try:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user
        )

        params['public_id'] = int(params['public_id'])
        params['predefined'] = params['predefined'] in ('true', 'True')
        params['is_global'] = params['is_global'] in ('true', 'True')
        params['fields'] = json.loads(params['fields'])

        current_template: CmdbSectionTemplate = section_templates_manager.get_section_template(params['public_id'])

        if not current_template:
            abort(404, "Target section template not found!")

        if current_template.predefined != params['predefined']:
            abort(400, "The 'predefined' property of a Section Template is not changable!")

        if current_template.type != params['type']:
            abort(400, "The 'type' of a Section Template is not changable!")

        section_templates_manager.update_section_template(params["public_id"], params)

        # Apply changes to all types and objects using the template
        section_templates_manager.handle_section_template_changes(params, current_template)

        return UpdateSingleResponse(True).make_response()
    except SectionTemplatesManagerGetError as err:
        LOGGER.error("[update_section_template] %s: %s", type(err), err, exc_info=True)
        abort(500, f"Failed to retrieve SectionTemplate with ID: {params['public_id']}!")
    except SectionTemplatesManagerUpdateError as err:
        LOGGER.error("[update_section_template] %s: %s", type(err), err, exc_info=True)
        abort(500, f"Failed to update SectionTemplate with ID: {params['public_id']}!")
    except Exception as err:
        LOGGER.error("[update_section_template] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating SectionTemplate with ID:{params['public_id']}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@section_template_blueprint.route('/<int:public_id>/', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@section_template_blueprint.protect(auth=True, right='base.framework.sectionTemplate.delete')
def delete_section_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    Delete a CmdbSectionTemplate by its public ID, with appropriate checks and permission handling.

    This function attempts to delete a CmdbSectionTemplate based on the provided public ID. Before deleting, 
    it checks whether the template is predefined (in which case it cannot be deleted) and whether it is 
    a global template that requires additional cleanup.

    Args:
        public_id (int): The public ID of the CmdbSectionTemplate to be deleted.
        request_user (CmdbUser): The user making the request, used for permission validation.

    Returns:
        DefaultResponse: A response indicating whether the deletion was successful
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

        if template_instance.is_global:
            section_templates_manager.cleanup_global_section_templates(template_instance.name, True)

        ack: bool = section_templates_manager.delete_section_template(public_id)
        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except SectionTemplatesManagerGetError as err:
        LOGGER.debug("[delete_section_template] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f"Failed to retrieve SectionTemplate with public_id: {public_id}!")
    except SectionTemplatesManagerDeleteError as err:
        LOGGER.debug("[delete_section_template] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to delete SectionTemplate with public_id: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_section_template] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the SectionTemplate with ID:{public_id}!")

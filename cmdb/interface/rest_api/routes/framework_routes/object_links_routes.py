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
Implementation of all API routes for CmdbObjectLinks
"""
from logging import Logger, getLogger
from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import ObjectLinksManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_link_model import CmdbObjectLink
from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import DeleteSingleResponse, InsertSingleResponse, GetMultiResponse

from cmdb.errors.manager.object_links_manager import (
    ObjectLinksManagerInsertError,
    ObjectLinksManagerGetError,
    ObjectLinksManagerGetObjectError,
    ObjectLinksManagerIterationError,
    ObjectLinksManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

links_blueprint = APIBlueprint('links', __name__)

LOGGER: Logger = getLogger(__name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@links_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@links_blueprint.protect(auth=True, right='base.framework.object.add')
def create_cmdb_object_link(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a new CmdbObjectLink in the database

    Args:
        `request_user` (CmdbUser): User requesting this operation

    Returns:
        `InsertSingleResponse`: Object containing the created public_id of the new CmdbObjectLink
    """
    try:
        object_link_creation_data: dict = request.json

        try:
            primary_id = object_link_creation_data['primary']
            secondary_id = object_link_creation_data['secondary']
        except KeyError:
            abort(400, "The 'primary' or 'secondary' key does not exist in the request data!")

        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(ManagerType.OBJECT_LINKS,
                                                                               request_user)

        # Confirm that this exact link does not exist
        object_link_exists = object_links_manager.check_link_exists(object_link_creation_data)

        if object_link_exists:
            abort(400, f"The ObjectLink between {primary_id} and {secondary_id} already exists!")

        result_id = object_links_manager.insert_object_link(object_link_creation_data)

        inserted_object_link = object_links_manager.get_object_link(result_id)

        if inserted_object_link:
            return InsertSingleResponse(CmdbObjectLink.to_json(inserted_object_link), result_id).make_response()

        abort(404, "Could not retrieve the created ObjectLink from the database!")
    except HTTPException as http_err:
        raise http_err
    except ObjectLinksManagerInsertError as err:
        LOGGER.error("[create_cmdb_object_link] ObjectLinksManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not create the ObjectLink in the database!")
    except ObjectLinksManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_link] ObjectLinksManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ObjectLink from the database!")
    except ObjectLinksManagerGetObjectError as err:
        LOGGER.error("[create_cmdb_object_link] ObjectLinksManagerGetObjectError: %s", err, exc_info=True)
        abort(404, "Could not retrieve an Object from the database which should be linked!")
    except Exception as err:
        LOGGER.error("[create_cmdb_object_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ObjectLink!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@links_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@links_blueprint.protect(auth=True, right='base.framework.object.view')
@links_blueprint.parse_collection_parameters()
def get_cmdb_object_links(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve multiple CmdbObjectLinks regarding the given 'params'

    Args:
        params (CollectionParameters): Filter for the CmdbObjectLinks
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        GetMultiResponse: Retrived CmdbObjectLinks based on the given 'params'
    """
    try:
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(ManagerType.OBJECT_LINKS,
                                                                               request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[CmdbObjectLink] = object_links_manager.iterate(builder_params)

        object_links = [CmdbObjectLink.to_json(object_link) for object_link in iteration_result.results]

        return GetMultiResponse(
                    object_links,
                    iteration_result.total,
                    params,
                    request.url,
                    request.method=="HEAD"
                ).make_response()
    except ObjectLinksManagerIterationError as err:
        LOGGER.error("[get_cmdb_object_links] ObjectLinksManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to iterate the ObjectLinks!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_links] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating ObjectLinks!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@links_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@links_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_cmdb_object_link(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a CmdbObjectLink with the given public_id

    Args:
        `public_id` (int): public_id of the CmdbObjectLink
        `request_user` (CmdbUser): User requesting this operation

    Returns:
        `DeleteSingleResponse`: CmdbObjectLink instance which was deleted
    """
    try:
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(ManagerType.OBJECT_LINKS,
                                                                               request_user)

        to_delete_object_link = object_links_manager.get_object_link(public_id)

        if to_delete_object_link:
            object_links_manager.delete_object_link(public_id)

            return DeleteSingleResponse(to_delete_object_link).make_response()

        abort(404, f"ObjectLink with ID:{public_id} not found!")
    except HTTPException as http_err:
        raise http_err
    except ObjectLinksManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object_link] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Could not delete the ObjectLink with ID:{public_id}!")
    except ObjectLinksManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_link] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectLink with ID:{public_id}  which should be deleted!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_object_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting ObjectLink with ID:{public_id}!")

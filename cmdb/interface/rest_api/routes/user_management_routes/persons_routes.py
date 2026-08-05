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
Implementation of all API routes for CmdbPersons
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import PersonsManager, PersonGroupsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.person_model import CmdbPerson

from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)

from cmdb.errors.manager.persons_manager import (
    PersonsManagerInsertError,
    PersonsManagerGetError,
    PersonsManagerUpdateError,
    PersonsManagerDeleteError,
    PersonsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

person_blueprint = APIBlueprint('person', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@person_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.add')
@person_blueprint.validate(CmdbPerson.SCHEMA)
def insert_cmdb_person(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an CmdbPerson into the database

    Args:
        data (CmdbPerson.SCHEMA): Data of the CmdbPerson which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbPerson and its public_id
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        result_id = persons_manager.insert_item(data)

        # Add the person to the selected groups
        selected_group_ids = data.get('groups', [])
        person_groups_manager.add_person_to_groups(result_id, selected_group_ids)

        created_person = persons_manager.get_item(result_id, as_dict=True)

        if not created_person:
            abort(404, "Could not retrieve the created Person from the database!")

        return InsertSingleResponse(created_person, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_person] PersonsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Person in the database!")
    except PersonsManagerGetError as err:
        LOGGER.error("[insert_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Person from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_person] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Person!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@person_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.view')
@person_blueprint.parse_collection_parameters()
def get_cmdb_persons(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbPersons

    Args:
        params (CollectionParameters): Filter for requested CmdbPersons
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbPersons matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbPerson] = persons_manager.iterate_items(builder_params)
        persons_list = [CmdbPerson.to_json(person) for person in iteration_result.results]

        api_response = GetMultiResponse(persons_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except PersonsManagerIterationError as err:
        LOGGER.error("[get_cmdb_persons] PersonsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Persons from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_persons] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Persons!")


@person_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.view')
def get_cmdb_person(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested CmdbPerson
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)

        requested_person = persons_manager.get_item(public_id, as_dict=True)

        if requested_person:
            return GetSingleResponse(requested_person, body = request.method == 'HEAD').make_response()

        abort(404, f"The Person with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except PersonsManagerGetError as err:
        LOGGER.error("[get_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_person] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Person with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.edit')
@person_blueprint.validate(CmdbPerson.SCHEMA)
def update_cmdb_person(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson which should be updated
        data (CmdbPerson.SCHEMA): New CmdbPerson data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbPerson
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        to_update_person = persons_manager.get_item(public_id, as_dict=True)

        if not to_update_person:
            abort(404, f"The Person with ID:{public_id} was not found!")

        # Check for added or removed groups
        existing_groups = set(to_update_person.get('groups', []))  # old group public_ids
        updated_groups = set(data.get('groups', []))  # new group public_ids

        groups_to_add = updated_groups - existing_groups  # New groups
        groups_to_remove = existing_groups - updated_groups  # Removed groups

        # Pin the public_id to the URL so a forged body public_id cannot rewrite the document identity
        data['public_id'] = public_id

        # Persist the Person first, then sync the reciprocal group membership only on success
        persons_manager.update_item(public_id, CmdbPerson.from_data(data))

        person_groups_manager.update_person_in_groups(public_id, groups_to_add, groups_to_remove)

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonsManagerGetError as err:
        LOGGER.error("[update_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID: {public_id} from the database!")
    except PersonsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_person] PersonsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Person with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_person] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Person with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.delete')
def delete_cmdb_person(public_id: int, request_user: CmdbUser) -> Response | None:
    """
    HTTP `DELETE` route to delete a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbPerson data
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        to_delete_person = persons_manager.get_item(public_id, as_dict=True)

        if not to_delete_person:
            abort(404, f"The Person with ID:{public_id} was not found!")

        persons_manager.delete_with_follow_up(public_id)

        # Delete the person from all groups
        person_groups_manager.delete_person_from_groups(public_id)

        return DeleteSingleResponse(to_delete_person).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_person] PersonsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Person with ID:{public_id}!")
    except PersonsManagerGetError as err:
        LOGGER.error("[delete_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_person] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Person with ID: {public_id}!")

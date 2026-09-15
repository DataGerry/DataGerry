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
Implementation of all API routes for CmdbPersonGroups

Every route here is ADMIN-level and rights-protected. Two things govern what the write routes do
beyond the plain CRUD:

**Membership is written on both sides.** The ``group_members`` list of the payload is stored on the
group AND mirrored into the ``groups`` of each named CmdbPerson, so the create and update routes make a
second, reciprocal call after the group itself is persisted. The ids are checked first
(``abort_on_unknown_references``): an unknown person id used to be stored and then mirrored into
nothing, leaving the two sides permanently disagreeing.

**Deleting is one manager call.** ``PersonGroupsManager.delete_with_follow_up`` clears the ISMS
references, removes the group from every person and deletes the document; the route does not clean
anything up itself, so a group deleted by any other caller is cleaned up the same way
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import PersonGroupsManager, PersonsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey

from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import (
    abort_on_unknown_references,
)

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

from cmdb.errors.manager.person_groups_manager import (
    PersonGroupsManagerInsertError,
    PersonGroupsManagerGetError,
    PersonGroupsManagerUpdateError,
    PersonGroupsManagerDeleteError,
    PersonGroupsManagerIterationError,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

person_group_blueprint = APIBlueprint('person_group', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@person_group_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.add')
@person_group_blueprint.validate(CmdbPersonGroup.SCHEMA)
def insert_cmdb_person_group(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an CmdbPersonGroup into the database

    Args:
        data (CmdbPersonGroup.SCHEMA): Data of the CmdbPersonGroup which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if a referenced CmdbPerson does not exist or the write fails,
                       404 if the created CmdbPersonGroup could not be read back,
                       500 on any unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPersonGroup and its public_id
    """
    try:
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)

        # Refuse a membership naming a person that does not exist, before anything is written
        selected_person_ids = data.get(PersonGroupKey.GROUP_MEMBERS.value) or []
        abort_on_unknown_references(persons_manager, selected_person_ids, 'Person')

        result_id = person_groups_manager.insert_item(data)

        # Add the new group to each of its selected member persons
        persons_manager.add_group_to_persons(result_id, selected_person_ids)

        created_person_group = person_groups_manager.get_item(result_id, as_dict=True)

        if not created_person_group:
            abort(404, "Could not retrieve the created PersonGroup from the database!")

        return InsertSingleResponse(created_person_group, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonGroupsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_person_group] PersonGroupsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new PersonGroup in the database!")
    except PersonGroupsManagerGetError as err:
        LOGGER.error("[insert_cmdb_person_group] PersonGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created PersonGroup from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_person_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the PersonGroup!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@person_group_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.view')
@person_group_blueprint.parse_collection_parameters()
def get_cmdb_person_groups(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbPersonGroups

    Args:
        params (CollectionParameters): Filter for requested CmdbPersonGroups
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if the CmdbPersonGroups could not be read, 500 on any unexpected error

    Returns:
        GetMultiResponse: All the CmdbPersonGroups matching the CollectionParameters
    """
    try:
        body = request_wants_body()

        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbPersonGroup] = person_groups_manager.iterate_items(builder_params)
        person_groups_list = [CmdbPersonGroup.to_json(person_group) for person_group in iteration_result.results]

        api_response = GetMultiResponse(person_groups_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except PersonGroupsManagerIterationError as err:
        LOGGER.error("[get_cmdb_person_groups] PersonGroupsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve PersonGroups from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_person_groups] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving PersonGroups!")


@person_group_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.view')
def get_cmdb_person_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPersonGroup

    Args:
        public_id (int): public_id of the CmdbPersonGroup
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPersonGroup carries the public_id, 400 if it could not be read,
                       500 on any unexpected error

    Returns:
        GetSingleResponse: The requested CmdbPersonGroup
    """
    try:
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        requested_person_group = person_groups_manager.get_item(public_id, as_dict=True)

        if requested_person_group:
            return GetSingleResponse(requested_person_group, body=request_wants_body()).make_response()

        abort(404, f"The PersonGroup with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except PersonGroupsManagerGetError as err:
        LOGGER.error("[get_cmdb_person_group] PersonGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the PersonGroup with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_person_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the PersonGroup with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@person_group_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.edit')
@person_group_blueprint.validate(CmdbPersonGroup.SCHEMA)
def update_cmdb_person_group(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbPersonGroup

    Args:
        public_id (int): public_id of the CmdbPersonGroup which should be updated
        data (CmdbPersonGroup.SCHEMA): New CmdbPersonGroup data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPersonGroup carries the public_id, 400 if a referenced CmdbPerson
                       does not exist or the write fails, 500 on any unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbPersonGroup
    """
    try:
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)

        to_update_person_group = person_groups_manager.get_item(public_id, as_dict=True)

        if not to_update_person_group:
            abort(404, f"The PersonGroup with ID:{public_id} was not found!")

        # Check for added or removed persons. Read with 'or []' rather than a .get() default: a
        # document written before updater_20260909 can carry null here, and set(None) raises
        existing_persons = set(to_update_person_group.get(PersonGroupKey.GROUP_MEMBERS.value) or [])
        updated_persons = set(data.get(PersonGroupKey.GROUP_MEMBERS.value) or [])

        persons_to_add = updated_persons - existing_persons  # New persons
        persons_to_remove = existing_persons - updated_persons  # Removed persons

        # Refuse a membership naming a person that does not exist, before anything is written
        abort_on_unknown_references(persons_manager, persons_to_add, 'Person')

        # Pin the public_id to the URL so a forged body public_id cannot rewrite the document identity
        data[PersonGroupKey.PUBLIC_ID.value] = public_id

        # Persist the PersonGroup first, then sync the reciprocal person membership only on success
        person_groups_manager.update_item(public_id, CmdbPersonGroup.from_data(data))

        persons_manager.update_group_in_persons(public_id, persons_to_add, persons_to_remove)

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonGroupsManagerGetError as err:
        LOGGER.error("[update_cmdb_person_group] PersonGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the PersonGroup with ID: {public_id} from the database!")
    except PersonGroupsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_person_group] PersonGroupsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the PersonGroup with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_person_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the PersonGroup with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@person_group_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.delete')
def delete_cmdb_person_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbPersonGroup

    Args:
        public_id (int): public_id of the CmdbPersonGroup which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPersonGroup carries the public_id, 400 if the read or the
                       deletion fails, 500 on any unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbPersonGroup data
    """
    try:
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        to_delete_person_group = person_groups_manager.get_item(public_id, as_dict=True)

        if not to_delete_person_group:
            abort(404, f"The PersonGroup with ID:{public_id} was not found!")

        # One call: the manager clears the ISMS references, removes the group from every CmdbPerson
        # listing it and deletes the document
        person_groups_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_person_group).make_response()
    except HTTPException as http_err:
        raise http_err
    except PersonGroupsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_person_group] PersonGroupsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the PersonGroup with ID:{public_id}!")
    except PersonGroupsManagerGetError as err:
        LOGGER.error("[delete_cmdb_person_group] PersonGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the PersonGroup with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_person_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the PersonGroup with ID: {public_id}!")

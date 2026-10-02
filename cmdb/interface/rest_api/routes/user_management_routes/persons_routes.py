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

Every route here is ADMIN-level and rights-protected. Two things govern what the write routes do
beyond the plain CRUD:

**Membership is written on both sides.** The ``groups`` list of the payload is stored on the person AND
mirrored into the ``group_members`` of the CmdbPersonGroups (``sync_membership``): the person is added to
every selected group and pulled from every group that lists them without being selected, so a save also
repairs a membership an earlier failure left one-sided. The ids are checked first
(``abort_on_unknown_references``): an unknown group id would be stored and then mirrored into nothing.

**Every write is all-or-nothing.** MongoDB runs standalone, so there is no transaction: each write route
records its writes in a WriteLedger (``undone_on_failure``) and a failure part-way undoes them - the person,
the reciprocal membership and, on a delete, the ISMS references ``PersonsManager.delete_with_follow_up``
clears (``record_delete_cascade``). An undo that cannot finish answers 500 naming what is still in effect
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response

from cmdb.manager import (
    ControlMeasureAssignmentManager,
    PersonsManager,
    PersonGroupsManager,
    RiskAssessmentManager,
)
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.person_model import CmdbPerson, PersonKey

from cmdb.models.person_group_model import PersonGroupKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import (
    record_delete_cascade,
    sync_membership,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    PERSON_CREATED_NOT_READABLE,
    PERSON_GROUP_LABEL,
    PERSON_WRITE_RESIDUE,
)

from cmdb.framework.results import IterationResult
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import abort_if_too_large, handle_route_errors, insert_request_user, verify_api_access
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
from cmdb.interface.rest_api.routes.routes_helper import (
    abort_on_unknown_references,
    pin_public_id,
    request_wants_body,
    require_created_item,
    undone_on_failure,
    update_item_from_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

person_blueprint = APIBlueprint('person', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@person_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.add')
@person_blueprint.validate(build_write_schema(CmdbPerson.SCHEMA))
@handle_route_errors("while creating the Person")
def insert_cmdb_person(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an CmdbPerson into the database

    Args:
        data (CmdbPerson.SCHEMA): Data of the CmdbPerson which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if a referenced CmdbPersonGroup does not exist or the write fails,
                       500 if the created CmdbPerson could not be read back, if a failed write could
                       not be fully undone, or on any unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPerson and its public_id
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)

        # Refuse a membership naming a group that does not exist, before anything is written
        selected_group_ids = data.get(PersonKey.GROUPS.value) or []
        abort_on_unknown_references(person_groups_manager, selected_group_ids, PERSON_GROUP_LABEL)

        with undone_on_failure(PERSON_WRITE_RESIDUE) as ledger:
            result_id = persons_manager.insert_item(data)
            ledger.inserted(persons_manager, result_id)

            sync_membership(
                ledger, person_groups_manager, PersonGroupKey.GROUP_MEMBERS.value, result_id, selected_group_ids
            )

        created_person = require_created_item(
            persons_manager.get_item(result_id, as_dict=True), PERSON_CREATED_NOT_READABLE
        )

        return InsertSingleResponse(created_person, result_id).make_response()
    except PersonsManagerInsertError as err:
        abort_if_too_large(err)
        LOGGER.error("[insert_cmdb_person] PersonsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Person in the database!")
    except PersonsManagerGetError as err:
        LOGGER.error("[insert_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Person from the database!")

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

    Raises:
        HTTPException: 400 if the CmdbPersons could not be read, 500 on any unexpected error

    Returns:
        GetMultiResponse: All the CmdbPersons matching the CollectionParameters
    """
    try:
        body = request_wants_body()

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
@handle_route_errors("while retrieving the Person with ID: {public_id}")
def get_cmdb_person(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPerson carries the public_id, 400 if it could not be read,
                       500 on any unexpected error

    Returns:
        GetSingleResponse: The requested CmdbPerson
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)

        requested_person = persons_manager.get_item(public_id, as_dict=True)

        if requested_person:
            return GetSingleResponse(requested_person, body=request_wants_body()).make_response()

        abort(404, f"The Person with ID:{public_id} was not found!")
    except PersonsManagerGetError as err:
        LOGGER.error("[get_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID: {public_id} from the database!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.edit')
@person_blueprint.validate(build_write_schema(CmdbPerson.SCHEMA))
@handle_route_errors("while updating the Person with ID: {public_id}")
def update_cmdb_person(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson which should be updated
        data (CmdbPerson.SCHEMA): New CmdbPerson data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPerson carries the public_id, 400 if a referenced CmdbPersonGroup
                       does not exist or the write fails, 500 if a failed write could not be fully
                       undone or on any unexpected error

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

        # Read with 'or []' rather than a .get() default: a document written before updater_20260909 can
        # carry null here, and set(None) raises
        existing_groups = set(to_update_person.get(PersonKey.GROUPS.value) or [])
        selected_groups = set(data.get(PersonKey.GROUPS.value) or [])

        # Refuse a membership naming a group that does not exist, before anything is written. A group the
        # person already listed is not re-checked: it may since have been deleted, and is then pulled
        abort_on_unknown_references(person_groups_manager, selected_groups - existing_groups, PERSON_GROUP_LABEL)
        pin_public_id(data, public_id)

        with undone_on_failure(PERSON_WRITE_RESIDUE) as ledger:
            ledger.updated(persons_manager, public_id, to_update_person)
            stored: dict[str, Any] = update_item_from_payload(persons_manager, public_id, CmdbPerson, data)

            sync_membership(
                ledger, person_groups_manager, PersonGroupKey.GROUP_MEMBERS.value, public_id, selected_groups
            )

        return UpdateSingleResponse(stored).make_response()
    except PersonsManagerGetError as err:
        LOGGER.error("[update_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID: {public_id} from the database!")
    except PersonsManagerUpdateError as err:
        abort_if_too_large(err)
        LOGGER.error("[update_cmdb_person] PersonsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Person with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right='base.user-management.person.delete')
@handle_route_errors("while deleting the Person with ID: {public_id}")
def delete_cmdb_person(public_id: int, request_user: CmdbUser) -> Response | None:
    """
    HTTP `DELETE` route to delete a single CmdbPerson

    Args:
        public_id (int): public_id of the CmdbPerson which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbPerson carries the public_id, 400 if the read or the deletion
                       fails, 500 if a failed deletion could not be fully undone or on any unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbPerson data
    """
    try:
        persons_manager: PersonsManager = ManagerProvider.get_manager(ManagerType.PERSON, request_user)
        person_groups_manager: PersonGroupsManager = ManagerProvider.get_manager(ManagerType.PERSON_GROUP,
                                                                                 request_user)
        risk_assessments_manager: RiskAssessmentManager = ManagerProvider.get_manager(
            ManagerType.RISK_ASSESSMENT, request_user
        )
        assignments_manager: ControlMeasureAssignmentManager = ManagerProvider.get_manager(
            ManagerType.CONTROL_MEASURE_ASSIGNMENT, request_user
        )

        to_delete_person = persons_manager.get_item(public_id, as_dict=True)

        if not to_delete_person:
            abort(404, f"The Person with ID:{public_id} was not found!")

        with undone_on_failure(PERSON_WRITE_RESIDUE) as ledger:
            # Every write of the cascade is recorded before the one call that makes them all
            record_delete_cascade(
                ledger,
                persons_manager,
                person_groups_manager,
                PersonGroupKey.GROUP_MEMBERS.value,
                to_delete_person,
                PersonReferenceType.PERSON,
                (risk_assessments_manager, assignments_manager),
            )
            persons_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_person).make_response()
    except PersonsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_person] PersonsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Person with ID:{public_id}!")
    except PersonsManagerGetError as err:
        LOGGER.error("[delete_cmdb_person] PersonsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Person with ID:{public_id} from the database!")

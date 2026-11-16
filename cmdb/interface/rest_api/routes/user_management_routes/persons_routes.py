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
The ``/persons`` routes - a layer over the objects of the Types carrying PERSON

A person is an object (``person_records_helper``); these routes keep the old request and response shape: a record
``{public_id, display_name, first_name, last_name, phone_number, email, groups}``, ``public_id`` the object id,
``groups`` the readable groups whose members hold it. Every route asks the object right of its operation and the
Type's ACL - the person rights are gone. ADMIN level, no licence gate: persons are needed in every edition
"""
from http import HTTPStatus
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.person_records_helper import (
    create_record,
    delete_record,
    list_records,
    read_record,
    update_record,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    PERSON_LABEL,
    RECORD_ACCESS_DENIED_MESSAGE,
    RECORD_CREATE_FAILED_MESSAGE,
    RECORD_DELETE_FAILED_MESSAGE,
    RECORD_READ_FAILED_MESSAGE,
    RECORD_UPDATE_FAILED_MESSAGE,
)
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerDeleteError,
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
)
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

MARKER: SpecialType = SpecialType.PERSON
PERSON_WRITE_SCHEMA: dict[str, Any] = build_write_schema(get_cmdb_person_schema())

person_blueprint = APIBlueprint('person', __name__)

# The manager failures of every route, by what was going on
_READ_FAILURES: dict[type[Exception], str] = {
    ObjectsManagerGetError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_LABEL),
    BaseManagerIterationError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_LABEL),
}
_CREATE_FAILURES: dict[type[Exception], str] = {
    **_READ_FAILURES,
    ObjectsManagerInsertError: RECORD_CREATE_FAILED_MESSAGE.format(label=PERSON_LABEL),
    ObjectsManagerUpdateError: RECORD_CREATE_FAILED_MESSAGE.format(label=PERSON_LABEL),
}
_ACCESS_DENIED: str = RECORD_ACCESS_DENIED_MESSAGE.format(label=PERSON_LABEL)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@person_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right=ObjectRightName.ADD.value)
@person_blueprint.validate(PERSON_WRITE_SCHEMA)
@handle_route_errors("while creating the Person")
@handle_manager_errors(_CREATE_FAILURES)
def insert_cmdb_person(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route creating a person - an object of the default PERSON Type, then its memberships

    Args:
        data (dict[str, Any]): The person record
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: what the object create answers (400 for a broken rule, 403 for the Type's ACL), 400 / 403
            for a group of ``groups`` that is none or the writer may not read or update, 500 without a default Type

    Returns:
        InsertSingleResponse: The new person record and its public_id
    """
    try:
        public_id: int = create_record(MARKER, data, request_user)

        return InsertSingleResponse(read_record(MARKER, public_id, request_user), public_id).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@person_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@person_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving Persons")
@handle_manager_errors(_READ_FAILURES)
def get_cmdb_persons(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route listing the persons of every PERSON Type the caller may READ

    The filter and the sort run on the record keys

    Args:
        params (CollectionParameters): Filter, sort and page
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the persons could not be read, 503 when the read ran past its time budget

    Returns:
        GetMultiResponse: The person records of the page and their total
    """
    records, total = list_records(MARKER, params, request_user)

    return GetMultiResponse(records, total, params, request.url, request_wants_body()).make_response()


@person_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while retrieving the Person with ID: {public_id}")
@handle_manager_errors(_READ_FAILURES)
def get_cmdb_person(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route reading one person

    Args:
        public_id (int): The person's object id
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 for an id naming no person, 403 for a person of a Type the caller may not READ

    Returns:
        GetSingleResponse: The person record
    """
    try:
        return GetSingleResponse(read_record(MARKER, public_id, request_user),
                                 body=request_wants_body()).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right=ObjectRightName.EDIT.value)
@person_blueprint.validate(PERSON_WRITE_SCHEMA)
@handle_route_errors("while updating the Person with ID: {public_id}")
@handle_manager_errors({**_READ_FAILURES, ObjectsManagerUpdateError: RECORD_UPDATE_FAILED_MESSAGE.format(
    label=PERSON_LABEL, public_id='{public_id}')})
def update_cmdb_person(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route updating a person - the keys the body carries; its memberships when it carries `groups`

    Args:
        public_id (int): The person's object id
        data (dict[str, Any]): The person record
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 / 403 as the read; what the object update answers; 400 / 403 for a group of ``groups``
            that is none or the writer may not read or update

    Returns:
        UpdateSingleResponse: The stored person record
    """
    try:
        update_record(MARKER, public_id, data, request_user)

        return UpdateSingleResponse(read_record(MARKER, public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@person_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_blueprint.protect(auth=True, right=ObjectRightName.DELETE.value)
@handle_route_errors("while deleting the Person with ID: {public_id}")
@handle_manager_errors({**_READ_FAILURES, ObjectsManagerDeleteError: RECORD_DELETE_FAILED_MESSAGE.format(
    label=PERSON_LABEL, public_id='{public_id}')})
def delete_cmdb_person(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting a person - the object delete, with its guards and clean-up

    The person leaves every group's members and every ISMS document; the delete is refused while it owns a risk
    assessment or is the only selection of a required person selector

    Args:
        public_id (int): The person's object id
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 / 403 as the read; what the object delete answers

    Returns:
        DeleteSingleResponse: The deleted person record
    """
    try:
        return DeleteSingleResponse(delete_record(MARKER, public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)
